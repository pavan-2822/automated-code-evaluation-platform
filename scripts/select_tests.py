#!/usr/bin/env python3
"""Select test targets from changed functions (fast local feedback).

Usage:
    python scripts/select_tests.py --changed evaluator/dispatcher.py:dispatch,detect_shape
    python scripts/select_tests.py --changed ci_healer/healer.py:process_run --full
    python scripts/select_tests.py --diff-file changes.diff

GUARDRAIL: this is for fast local feedback only. The full suite still
runs in CI. An unknown changed function falls back to the full suite.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci_healer.test_filter import (  # noqa: E402
    FULL_SUITE_TARGETS, parse_git_diff, select_tests,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Select tests by changed function")
    parser.add_argument("--changed", action="append", default=[],
                        help="file:function1,function2 (repeatable)")
    parser.add_argument("--diff-file", default=None, help="unified diff file to parse")
    parser.add_argument("--full", action="store_true", help="select the full suite")
    args = parser.parse_args(argv)

    functions = []
    for spec in args.changed:
        if ":" in spec:
            _, names = spec.split(":", 1)
            functions.extend(name.strip() for name in names.split(",") if name.strip())
        else:
            functions.append(spec)
    if args.diff_file:
        diff = Path(args.diff_file).read_text(encoding="utf-8")
        for names in parse_git_diff(diff).values():
            functions.extend(names)

    available = sorted(str(p) for p in Path("tests").glob("test_*.py"))
    selected = select_tests(functions, available_tests=available, full=args.full)
    for target in selected.targets:
        print(target)
    print(f"# {selected.reason}", file=sys.stderr)
    if selected.full_suite:
        print("# Full suite still runs in CI.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
