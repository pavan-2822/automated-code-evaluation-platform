"""Command-line interface for the CI healer.

Usage:
    python -m ci_healer.cli --repo owner/repo --run-id 123 [--dry-run]
                             [--max-retries 2]
                             [--jobs-file jobs.json]
                             [--state healer-state.json]
                             [--audit healer-audit.jsonl]

``--jobs-file`` supplies jobs offline as JSON:
``{"jobs": [{"id": 1, "name": "test", "conclusion": "failure",
"log": "..."}]}``. Without it, jobs are fetched from the GitHub API
(requires ``GITHUB_TOKEN`` unless ``--dry-run`` is given).

Exit codes: 0 when every failed job was retried (or would be, in
dry-run) or there were no failed jobs; 2 when any failure was
UNKNOWN -- a visible stop, not a silent success.
"""

from __future__ import annotations

import argparse
import json
import sys

from .github_client import GitHubClient
from .healer import process_run


def build_parser():
    parser = argparse.ArgumentParser(description="Self-healing CI assistant (bounded, audited)")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--jobs-file", default=None,
                        help="JSON file with jobs (offline mode)")
    parser.add_argument("--state", default="healer-state.json")
    parser.add_argument("--audit", default="healer-audit.jsonl")
    return parser


def load_jobs_from_file(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    return data.get("jobs", [])


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.jobs_file:
        jobs = load_jobs_from_file(args.jobs_file)
        client = GitHubClient(dry_run=args.dry_run)
    else:
        client = GitHubClient(dry_run=args.dry_run)
        jobs = client.list_jobs(args.repo, args.run_id)
        # Live job listings do not include logs; classification then
        # uses conclusions only. Supplying --jobs-file with logs is
        # the accurate offline path, and is what the demo uses.
    decisions = process_run(
        args.repo, args.run_id, jobs, client=client,
        max_retries=args.max_retries, state_path=args.state,
        audit_path=args.audit, dry_run=args.dry_run,
    )
    unknown = [d for d in decisions if d.mode_slug == "unknown"]
    for decision in decisions:
        status = "RETRY" if decision.retried else (
            "WOULD-RETRY" if decision.would_retry else "SKIP")
        print(f"[{status}] {decision.job_name}: {decision.mode_name} -- {decision.reason}")
    if unknown:
        print("STOP: unknown failure(s) present; not retried. Investigate manually.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
