"""Minimal GitHub REST API wrapper, standard library only.

Token handling rules, enforced by design:
- The token comes from the ``GITHUB_TOKEN`` environment variable only.
  It is never hardcoded, never written to a file, and never logged.
  Log lines contain only the method, path, and status -- never headers.
- Dry-run mode short-circuits mutating calls before any HTTP is made,
  so a dry run cannot accidentally rerun anything.
- Rate limits (403/429) are handled with bounded backoff: the server's
  ``Retry-After`` header wins, otherwise ``X-RateLimit-Reset`` is used,
  capped so a single call never sleeps for an unbounded time.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

BASE_URL = "https://api.github.com"
# A single request never sleeps longer than this on a rate limit.
MAX_RATE_LIMIT_WAIT_SECONDS = 60


class GitHubError(Exception):
    """A non-rate-limit GitHub API failure."""


class GitHubClient:
    """A small wrapper around the GitHub Actions API."""

    def __init__(self, token=None, dry_run=False, base_url=BASE_URL,
                 max_retries=3, sleep=time.sleep):
        self.dry_run = dry_run
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._sleep = sleep
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        if not dry_run and not self.token:
            raise ValueError(
                "GITHUB_TOKEN is not set; set it in the environment or "
                "use dry-run mode"
            )

    # -- low-level HTTP (separated so tests can stub _do_http) --------

    def _do_http(self, request):
        """Perform one request; return (status, headers dict, body)."""
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read()

    def _rate_limit_wait(self, headers):
        """Seconds to wait for a rate-limit response, bounded."""
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), MAX_RATE_LIMIT_WAIT_SECONDS)
            except ValueError:
                pass
        reset = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")
        if reset:
            try:
                wait = float(reset) - time.time()
                return max(0.0, min(wait, MAX_RATE_LIMIT_WAIT_SECONDS))
            except ValueError:
                pass
        return 1.0

    def _request(self, method, path, payload=None):
        """Make a request with bounded rate-limit retries."""
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode() if payload is not None else None
        last_status = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(url, data=body, method=method)
            request.add_header("Accept", "application/vnd.github+json")
            if self.token:
                request.add_header("Authorization", f"Bearer {self.token}")
            if body is not None:
                request.add_header("Content-Type", "application/json")
            status, headers, raw = self._do_http(request)
            last_status = status
            # Only method/path/status are ever logged -- never headers.
            log.info("%s %s -> %s (attempt %d)", method, path, status, attempt + 1)
            if status in (403, 429) and attempt < self.max_retries:
                wait = self._rate_limit_wait(headers)
                log.warning("rate limited; waiting %.1fs before retry", wait)
                self._sleep(wait)
                continue
            if 200 <= status < 300:
                return json.loads(raw) if raw else {}
            raise GitHubError(f"{method} {path} failed with status {status}")
        raise GitHubError(f"{method} {path} failed after retries (last status {last_status})")

    # -- Actions API ---------------------------------------------------

    def list_jobs(self, repo, run_id):
        """List jobs for a workflow run (read-only)."""
        data = self._request("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs")
        return data.get("jobs", [])

    def get_run(self, repo, run_id):
        """Fetch one workflow run (read-only)."""
        return self._request("GET", f"/repos/{repo}/actions/runs/{run_id}")

    def rerun_failed_jobs(self, repo, run_id):
        """Rerun failed jobs, or log the action in dry-run mode.

        In dry-run mode this returns a description of the action and
        makes no HTTP call at all.
        """
        if self.dry_run:
            log.info("[dry-run] would rerun failed jobs for %s run %s", repo, run_id)
            return {"dry_run": True, "action": "rerun_failed_jobs",
                    "repo": repo, "run_id": run_id}
        return self._request(
            "POST", f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs"
        )
