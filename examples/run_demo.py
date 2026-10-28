#!/usr/bin/env python3
"""End-to-end demo: dispatcher + evaluator for every input shape.

Runs each example submission in ``examples/`` through the dispatcher
for problem ``two-sum`` and prints the detected shape and the
reference-solution verdict per case. No network, no Docker needed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluator.dispatcher import dispatch  # noqa: E402

EXAMPLES = [
    "submission_json_object.json",
    "submission_json_list.json",
    "submission_jsonl.jsonl",
    "submission_plain.txt",
    "submission_csv.csv",
    "submission_keyvalue.txt",
]


def main():
    here = Path(__file__).resolve().parent
    total = passed = 0
    for name in EXAMPLES:
        text = (here / name).read_text(encoding="utf-8")
        outcomes = dispatch("two-sum", text)
        shape = outcomes[0].case.shape if outcomes else "?"
        line = ", ".join(
            f"case {i}: {'PASS' if o.passed else 'FAIL'} (actual={o.actual})"
            for i, o in enumerate(outcomes)
        )
        print(f"{name} [{shape}] -> {line}")
        total += len(outcomes)
        passed += sum(1 for o in outcomes if o.passed)
    print(f"\nDemo total: {passed}/{total} cases passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
