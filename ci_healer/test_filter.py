"""Function-level test filtering for fast local feedback.

GUARDRAIL: filtering is for fast local feedback only. The full test
suite still runs in CI (see ``.github/workflows/ci.yml``). Filtering
must never silently drop tests: an unknown changed function falls back
to the full suite, and ``--full`` always selects everything.

Selection rules, in order:
1. ``full=True`` -> the full suite.
2. A changed function listed in the explicit mapping -> its test files.
3. A changed function whose name matches an available test file name
   (e.g. ``dispatcher`` matches ``tests/test_dispatcher.py``) -> that file.
4. Anything else -> the full suite (safe fallback, never an empty run).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field


# Explicit mapping for this repository. Keys are changed function
# names; values are the test files that cover them.
DEFAULT_MAPPING = {
    "dispatch": ["tests/test_dispatcher.py"],
    "detect_shape": ["tests/test_dispatcher.py"],
    "parse_cases": ["tests/test_dispatcher.py"],
    "two_sum": ["tests/test_evaluator.py"],
    "sorted_squares": ["tests/test_evaluator.py"],
    "fibonacci": ["tests/test_evaluator.py"],
    "valid_parentheses": ["tests/test_evaluator.py"],
    "evaluate": ["tests/test_evaluator.py"],
    "classify": ["tests/test_healer.py"],
    "process_run": ["tests/test_healer.py"],
    "select_tests": ["tests/test_filter.py"],
}

FULL_SUITE_TARGETS = ["tests"]


@dataclass
class SelectedTests:
    """The outcome of a filtering decision."""

    targets: list = field(default_factory=list)
    full_suite: bool = False
    reason: str = ""

    def to_dict(self):
        return {"targets": self.targets, "full_suite": self.full_suite,
                "reason": self.reason}


def select_tests(changed_functions, mapping=None, available_tests=None, full=False):
    """Select test targets for ``changed_functions`` (function names)."""
    if full:
        return SelectedTests(targets=list(FULL_SUITE_TARGETS), full_suite=True,
                             reason="--full requested")
    mapping = mapping if mapping is not None else DEFAULT_MAPPING
    available = available_tests or []
    targets = []
    for name in changed_functions:
        if name in mapping:
            for target in mapping[name]:
                if target not in targets:
                    targets.append(target)
            continue
        # Name matching against available test files.
        matched = [t for t in available if name and name in t]
        if matched:
            for target in matched:
                if target not in targets:
                    targets.append(target)
            continue
        # Unknown function: fall back to the full suite, safely.
        return SelectedTests(targets=list(FULL_SUITE_TARGETS), full_suite=True,
                             reason=f"unknown function {name!r}; falling back to full suite")
    if not targets:
        return SelectedTests(targets=list(FULL_SUITE_TARGETS), full_suite=True,
                             reason="no changed functions; running full suite")
    return SelectedTests(targets=targets, full_suite=False,
                         reason="selected by function mapping/name matching")


def parse_git_diff(diff_text):
    """Parse a unified diff into ``{file: [function names]}``.

    Only ``def`` lines following a file header are collected. When git
    is unavailable, callers can pass diff text from a file instead.
    """
    changed = {}
    current_file = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/"):].strip()
            changed.setdefault(current_file, [])
        elif line.startswith("+") and not line.startswith("+++") and current_file:
            match = re.match(r"\+\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", line)
            if match and match.group(1) not in changed[current_file]:
                changed[current_file].append(match.group(1))
    return {path: fns for path, fns in changed.items() if fns}


def changed_functions_from_git(ref="HEAD"):
    """Return parsed diff functions via git, or {} if git is absent."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--unified=0", ref],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        return {}
    return parse_git_diff(proc.stdout)
