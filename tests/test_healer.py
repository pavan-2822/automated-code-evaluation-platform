"""Tests for the CI failure classifier, GitHub client, and healer.

The six failure modes tested here are this repository's own
definitions (see ci_healer/classifier.py), not any company's modes.
"""

import json
import os
import tempfile
import unittest

from ci_healer.classifier import FAILURE_MODES, UNKNOWN, classify
from ci_healer.github_client import GitHubClient
from ci_healer.healer import load_state, process_run


def job(name, log, conclusion="failure"):
    return {"id": 1, "name": name, "conclusion": conclusion, "log": log}


class TestClassifier(unittest.TestCase):
    def test_all_six_modes_classify(self):
        signals = {
            "disk-quota": "Error: No space left on device while writing image",
            "dependency-network": "pip install failed: Temporary failure in name resolution",
            "docker-pull": "failed to pull image: toomanyrequests: rate limit exceeded",
            "runner-lost": "Lost communication with the server during job",
            "cache-corruption": "Cache restore failed: checksum mismatch in cache",
            "service-startup-timeout": "Timed out waiting for service postgres to be ready",
        }
        self.assertEqual(len(FAILURE_MODES), 6)
        for slug, log_text in signals.items():
            with self.subTest(slug=slug):
                self.assertEqual(classify(log_text).slug, slug)

    def test_runner_lost_by_conclusion(self):
        self.assertEqual(classify("", conclusion="cancelled").slug, "runner-lost")

    def test_unknown_is_not_a_defined_mode(self):
        mode = classify("AssertionError: expected 2, got 3 in test_login")
        self.assertIs(mode, UNKNOWN)
        self.assertFalse(mode.retryable)


class FakeClient:
    """Records rerun calls; stands in for GitHubClient in healer tests."""

    def __init__(self):
        self.dry_run = False
        self.rerun_calls = []

    def rerun_failed_jobs(self, repo, run_id):
        self.rerun_calls.append((repo, run_id))
        return {"ok": True}


class TestHealer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state.json")
        self.audit = os.path.join(self.tmp.name, "audit.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_failure_is_retried(self):
        client = FakeClient()
        decisions = process_run("o/r", 42, [job("test", "No space left on device")],
                                client=client, state_path=self.state,
                                audit_path=self.audit)
        self.assertTrue(decisions[0].retried)
        self.assertEqual(client.rerun_calls, [("o/r", 42)])

    def test_unknown_failure_is_never_retried(self):
        client = FakeClient()
        decisions = process_run("o/r", 42, [job("test", "AssertionError in test_login")],
                                client=client, state_path=self.state,
                                audit_path=self.audit)
        self.assertFalse(decisions[0].retried)
        self.assertFalse(decisions[0].would_retry)
        self.assertEqual(client.rerun_calls, [])

    def test_retry_budget_enforced_and_persisted(self):
        client = FakeClient()
        jobs = [job("test", "No space left on device")]
        for _ in range(3):
            decisions = process_run("o/r", 42, jobs, client=client,
                                    max_retries=2, state_path=self.state,
                                    audit_path=self.audit)
        self.assertFalse(decisions[0].retried)
        self.assertIn("budget exhausted", decisions[0].reason)
        self.assertEqual(len(client.rerun_calls), 2)
        # A fresh process_run reading the same state file is still blocked.
        decisions = process_run("o/r", 42, jobs, client=client,
                                max_retries=2, state_path=self.state,
                                audit_path=self.audit)
        self.assertFalse(decisions[0].retried)

    def test_idempotency_via_state_file(self):
        client = FakeClient()
        jobs = [job("test", "Cache restore failed")]
        process_run("o/r", 7, jobs, client=client, state_path=self.state,
                    audit_path=self.audit)
        state = load_state(self.state)
        self.assertEqual(state["attempts"].get("7:cache-corruption:test"), 1)

    def test_dry_run_consumes_no_budget_and_makes_no_calls(self):
        client = FakeClient()
        jobs = [job("test", "No space left on device")]
        decisions = process_run("o/r", 42, jobs, client=client, dry_run=True,
                                state_path=self.state, audit_path=self.audit)
        self.assertTrue(decisions[0].would_retry)
        self.assertFalse(decisions[0].retried)
        self.assertEqual(client.rerun_calls, [])
        self.assertEqual(load_state(self.state)["attempts"], {})

    def test_audit_log_appends_one_record_per_decision(self):
        process_run("o/r", 42, [job("test", "No space left on device"),
                                job("other", "AssertionError")],
                    client=FakeClient(), state_path=self.state,
                    audit_path=self.audit)
        with open(self.audit, encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["mode_slug"], "disk-quota")
        self.assertEqual(records[1]["mode_slug"], "unknown")

    def test_successful_jobs_are_skipped(self):
        decisions = process_run("o/r", 42, [job("test", "", conclusion="success")],
                                client=FakeClient(), state_path=self.state,
                                audit_path=self.audit)
        self.assertEqual(decisions, [])

    def test_original_logs_are_not_overwritten(self):
        # The healer only reads logs and writes state/audit files; the
        # job dict (standing in for the log source) is unchanged.
        jobs = [job("test", "No space left on device")]
        process_run("o/r", 42, jobs, client=FakeClient(),
                    state_path=self.state, audit_path=self.audit)
        self.assertEqual(jobs[0]["log"], "No space left on device")


class TestGitHubClient(unittest.TestCase):
    def test_dry_run_makes_no_http_call(self):
        client = GitHubClient(dry_run=True)

        def _boom(request):
            raise AssertionError("no HTTP should happen in dry-run")

        client._do_http = _boom
        result = client.rerun_failed_jobs("o/r", 42)
        self.assertTrue(result["dry_run"])

    def test_token_comes_from_environment_only(self):
        os.environ["GITHUB_TOKEN"] = "test-token-that-is-never-logged"
        try:
            client = GitHubClient(dry_run=False)
            self.assertEqual(client.token, "test-token-that-is-never-logged")
        finally:
            del os.environ["GITHUB_TOKEN"]
        with self.assertRaises(ValueError):
            GitHubClient(dry_run=False)

    def test_rate_limit_retries_with_bounded_backoff(self):
        sleeps = []
        client = GitHubClient(dry_run=True, sleep=sleeps.append, max_retries=2)
        calls = {"n": 0}

        def fake_http(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return 429, {"Retry-After": "5"}, b"{}"
            return 200, {}, json.dumps({"jobs": []}).encode()

        client._do_http = fake_http
        jobs = client.list_jobs("o/r", 42)
        self.assertEqual(jobs, [])
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [5.0])

    def test_rate_limit_wait_is_capped(self):
        client = GitHubClient(dry_run=True)
        wait = client._rate_limit_wait({"Retry-After": "99999"})
        self.assertEqual(wait, 60)


if __name__ == "__main__":
    unittest.main()
