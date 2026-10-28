"""Run candidate solutions against normalised cases.

Security boundary, stated plainly: running a code *string* here uses a
separate subprocess with a timeout, but a subprocess is **not** a
sandbox. A malicious program can still read files, use the network, or
exhaust resources within the timeout. This local runner is therefore
for trusted local demo/test code only. In production, untrusted code
must run inside a real isolation boundary -- a locked-down container
with no network, a read-only filesystem, and resource limits -- which
is outside what this repository proves.

A Python *callable* is run in-process (there is no reliable way to
enforce a timeout on in-process Python), so that path is also for
trusted code only. The subprocess path is the one to use for code
strings, and it enforces a per-case timeout.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field


@dataclass
class CaseResult:
    """The outcome of one case."""

    case_index: int
    passed: bool
    actual: object = None
    expected: object = None
    error: str | None = None
    timed_out: bool = False
    duration_seconds: float = 0.0

    def to_dict(self):
        return {
            "case_index": self.case_index,
            "passed": self.passed,
            "actual": self.actual,
            "expected": self.expected,
            "error": self.error,
            "timed_out": self.timed_out,
            "duration_seconds": round(self.duration_seconds, 3),
        }


@dataclass
class EvaluationResult:
    """The structured outcome of a whole evaluation run."""

    problem_id: str
    results: list = field(default_factory=list)

    @property
    def total(self):
        return len(self.results)

    @property
    def passed_count(self):
        return sum(1 for result in self.results if result.passed)

    @property
    def failed_count(self):
        return self.total - self.passed_count

    @property
    def all_passed(self):
        return self.total > 0 and self.failed_count == 0

    def to_dict(self):
        return {
            "problem_id": self.problem_id,
            "total": self.total,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "all_passed": self.all_passed,
            "results": [result.to_dict() for result in self.results],
        }


def evaluate_callable(fn, cases, problem_id=""):
    """Run a trusted in-process callable against ``cases``.

    Exceptions are captured per case; one failing case does not stop
    the remaining cases. No timeout is enforced on this path (see the
    module docstring).
    """
    results = []
    for index, case in enumerate(cases):
        started = time.monotonic()
        try:
            actual = fn(*case.inputs)
            results.append(
                CaseResult(
                    case_index=index,
                    passed=actual == case.expected,
                    actual=actual,
                    expected=case.expected,
                    duration_seconds=time.monotonic() - started,
                )
            )
        except Exception as exc:  # noqa: BLE001 - captured per case
            results.append(
                CaseResult(
                    case_index=index,
                    passed=False,
                    expected=case.expected,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_seconds=time.monotonic() - started,
                )
            )
    return EvaluationResult(problem_id=problem_id, results=results)


# The harness run inside the subprocess. It reads one case as JSON on
# stdin, execs the candidate code, calls ``solve`` with the case inputs,
# and prints a JSON result. Keeping it small and explicit matters: the
# parent never trusts the child's stdout beyond this one JSON object.
_HARNESS = textwrap.dedent(
    """
    import json, sys, traceback
    payload = json.load(sys.stdin)
    namespace = {}
    try:
        exec(payload["code"], namespace)
        fn = namespace.get("solve")
        if fn is None:
            raise NameError("candidate code must define a function named 'solve'")
        actual = fn(*payload["inputs"])
        print(json.dumps({"ok": True, "actual": actual}))
    except Exception:
        print(json.dumps({"ok": False, "error": traceback.format_exc(limit=3)}))
    """
)


def _run_code_case(code, case, timeout):
    """Run one case in its own subprocess; return a CaseResult."""
    started = time.monotonic()
    payload = json.dumps({"code": code, "inputs": case.inputs})
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _HARNESS],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CaseResult(
            case_index=-1,
            passed=False,
            expected=case.expected,
            error=f"timeout after {timeout} seconds",
            timed_out=True,
            duration_seconds=time.monotonic() - started,
        )
    duration = time.monotonic() - started
    try:
        outcome = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return CaseResult(
            case_index=-1,
            passed=False,
            expected=case.expected,
            error=f"candidate harness produced no JSON output; stderr: {proc.stderr[:500]}",
            duration_seconds=duration,
        )
    if not outcome.get("ok"):
        return CaseResult(
            case_index=-1,
            passed=False,
            expected=case.expected,
            error=outcome.get("error", "unknown candidate error")[-500:],
            duration_seconds=duration,
        )
    actual = outcome["actual"]
    return CaseResult(
        case_index=-1,
        passed=actual == case.expected,
        actual=actual,
        expected=case.expected,
        duration_seconds=duration,
    )


def evaluate_code(code, cases, problem_id="", timeout=5.0):
    """Run a code string (must define ``solve``) against ``cases``.

    Each case runs in its own subprocess with a ``timeout`` (seconds).
    A timeout or exception in one case is recorded for that case only.
    """
    results = []
    for index, case in enumerate(cases):
        result = _run_code_case(code, case, timeout)
        result.case_index = index
        results.append(result)
    return EvaluationResult(problem_id=problem_id, results=results)


def evaluate(candidate, cases, problem_id="", timeout=5.0):
    """Dispatch to the callable or code-string evaluator.

    ``candidate`` may be a callable (trusted, in-process) or a string
    (subprocess, per-case timeout). Anything else raises ``TypeError``.
    """
    if callable(candidate):
        return evaluate_callable(candidate, cases, problem_id=problem_id)
    if isinstance(candidate, str):
        return evaluate_code(candidate, cases, problem_id=problem_id, timeout=timeout)
    raise TypeError("candidate must be a callable or a code string")
