"""Healer orchestration: classify, budget, audit, never hide failures.

Rules enforced here:
- Retry budget is per (run_id, signature), where signature is
  ``<mode-slug>:<job-name>``. It defaults to 2 attempts, is
  configurable, and is persisted in a JSON state file, so rerunning
  the healer does not reset the budget (idempotency).
- Dry-run decisions never consume budget and never call mutating APIs.
- Unknown failures are never retried. They are recorded in the audit
  log and reported as a visible stop, not swallowed.
- Original logs are never deleted or overwritten. The healer only
  reads logs supplied to it and writes two new files of its own: the
  state file and the audit JSONL file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .classifier import UNKNOWN, classify_job


@dataclass
class Decision:
    """One decision about one failed job."""

    run_id: int
    job_id: object
    job_name: str
    mode_slug: str
    mode_name: str
    signature: str
    attempts_used: int
    retried: bool
    would_retry: bool
    reason: str
    action: str

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "mode_slug": self.mode_slug,
            "mode_name": self.mode_name,
            "signature": self.signature,
            "attempts_used": self.attempts_used,
            "retried": self.retried,
            "would_retry": self.would_retry,
            "reason": self.reason,
            "action": self.action,
        }


def load_state(path):
    """Load the retry-budget state file; missing/corrupt -> empty."""
    if not path or not os.path.exists(path):
        return {"attempts": {}}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("attempts"), dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"attempts": {}}


def save_state(path, state):
    """Save state atomically-ish (write temp file, then replace)."""
    if not path:
        return
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def append_audit(path, decision):
    """Append one JSONL audit record. Never overwrites existing records."""
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(decision.to_dict(), sort_keys=True) + "\n")


def process_run(repo, run_id, jobs, client=None, max_retries=2,
                state_path=None, audit_path=None, dry_run=False):
    """Decide and (unless dry-run) act on every failed job in ``jobs``.

    ``jobs`` are dicts with ``id``, ``name``, ``conclusion`` and
    ``log`` keys. Successful jobs are skipped. Returns a list of
    Decision objects, one per failed job.
    """
    state = load_state(state_path)
    attempts = state.setdefault("attempts", {})
    decisions = []
    for job in jobs:
        if job.get("conclusion") == "success":
            continue
        mode = classify_job(job)
        signature = f"{mode.slug}:{job.get('name', job.get('id', ''))}"
        key = f"{run_id}:{signature}"
        used = int(attempts.get(key, 0))
        decision = Decision(
            run_id=run_id,
            job_id=job.get("id"),
            job_name=job.get("name", ""),
            mode_slug=mode.slug,
            mode_name=mode.name,
            signature=signature,
            attempts_used=used,
            retried=False,
            would_retry=False,
            reason="",
            action=mode.recovery_action,
        )
        if mode is UNKNOWN or not mode.retryable:
            decision.reason = "unknown failure -- not retried; left visible"
        elif used >= max_retries:
            decision.attempts_used = used
            decision.reason = (
                f"retry budget exhausted ({used}/{max_retries} attempts)"
            )
        elif dry_run or (client is not None and getattr(client, "dry_run", False)):
            decision.would_retry = True
            decision.reason = "dry-run -- would rerun, budget not consumed"
        else:
            attempts[key] = used + 1
            decision.attempts_used = used + 1
            decision.retried = True
            decision.would_retry = True
            decision.reason = f"retrying ({used + 1}/{max_retries} attempts)"
            if client is not None:
                client.rerun_failed_jobs(repo, run_id)
            # If no client was supplied, the decision is recorded but
            # no API call is made; callers use this for offline tests.
        decisions.append(decision)
        append_audit(audit_path, decision)
    save_state(state_path, state)
    return decisions
