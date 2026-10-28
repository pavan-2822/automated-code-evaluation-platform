"""Tests for function-level test filtering and its guardrails."""

import unittest

from ci_healer.test_filter import parse_git_diff, select_tests


class TestSelectTests(unittest.TestCase):
    def test_mapped_function_selects_its_tests(self):
        selected = select_tests(["dispatch"])
        self.assertEqual(selected.targets, ["tests/test_dispatcher.py"])
        self.assertFalse(selected.full_suite)

    def test_name_matching_selects_available_test_file(self):
        selected = select_tests(["dispatcher"],
                                mapping={},
                                available_tests=["tests/test_dispatcher.py"])
        self.assertEqual(selected.targets, ["tests/test_dispatcher.py"])

    def test_unknown_function_falls_back_to_full_suite(self):
        selected = select_tests(["some_function_nobody_mapped"])
        self.assertTrue(selected.full_suite)
        self.assertEqual(selected.targets, ["tests"])
        self.assertIn("full suite", selected.reason)

    def test_full_flag_always_selects_full_suite(self):
        selected = select_tests(["dispatch"], full=True)
        self.assertTrue(selected.full_suite)
        self.assertEqual(selected.targets, ["tests"])

    def test_no_changed_functions_selects_full_suite(self):
        selected = select_tests([])
        self.assertTrue(selected.full_suite)

    def test_multiple_functions_merge_targets_without_duplicates(self):
        selected = select_tests(["dispatch", "detect_shape"])
        self.assertEqual(selected.targets, ["tests/test_dispatcher.py"])


class TestParseGitDiff(unittest.TestCase):
    def test_parses_added_functions_per_file(self):
        diff = ("diff --git a/evaluator/dispatcher.py b/evaluator/dispatcher.py\n"
                "+++ b/evaluator/dispatcher.py\n"
                "@@ -1,0 +1,2 @@\n"
                "+def dispatch(problem_id, text):\n"
                "+    pass\n"
                "+++ b/ci_healer/healer.py\n"
                "+def process_run():\n")
        parsed = parse_git_diff(diff)
        self.assertEqual(parsed["evaluator/dispatcher.py"], ["dispatch"])
        self.assertEqual(parsed["ci_healer/healer.py"], ["process_run"])

    def test_removed_lines_are_not_counted(self):
        diff = ("+++ b/evaluator/dispatcher.py\n"
                "-def old_function():\n"
                "+def new_function():\n")
        parsed = parse_git_diff(diff)
        self.assertEqual(parsed["evaluator/dispatcher.py"], ["new_function"])


if __name__ == "__main__":
    unittest.main()
