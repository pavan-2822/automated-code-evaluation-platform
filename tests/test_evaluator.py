"""Tests for reference solutions and the candidate evaluator.

Reference-solution tests use independent, hand-computed expectations --
they do not compare a function with itself.
"""

import unittest

from evaluator.dispatcher import Case
from evaluator.evaluator import evaluate, evaluate_callable, evaluate_code
from evaluator.reference_solutions import (
    fibonacci,
    sorted_squares,
    two_sum,
    valid_parentheses,
)


def case(inputs, expected):
    return Case(inputs=inputs, expected=expected, raw="", shape="test")


class TestReferenceSolutions(unittest.TestCase):
    def test_two_sum_basic_and_duplicate_values(self):
        self.assertEqual(two_sum([2, 7, 11, 15], 9), [0, 1])
        self.assertEqual(two_sum([3, 3], 6), [0, 1])
        with self.assertRaises(ValueError):
            two_sum([1, 2, 3], 100)

    def test_sorted_squares_includes_negatives(self):
        self.assertEqual(sorted_squares([-4, -1, 0, 3, 10]), [0, 1, 9, 16, 100])
        self.assertEqual(sorted_squares([]), [])

    def test_fibonacci_known_values(self):
        self.assertEqual([fibonacci(n) for n in range(8)], [0, 1, 1, 2, 3, 5, 8, 13])
        with self.assertRaises(ValueError):
            fibonacci(-1)

    def test_valid_parentheses(self):
        self.assertTrue(valid_parentheses("()[]{}"))
        self.assertTrue(valid_parentheses(""))
        self.assertFalse(valid_parentheses("(]"))
        self.assertFalse(valid_parentheses("(()"))


class TestEvaluateCallable(unittest.TestCase):
    def test_pass_fail_and_exception_are_per_case(self):
        cases = [case([[2, 7, 11, 15], 9], [0, 1]),
                 case([[2, 7, 11, 15], 9], [0, 2]),
                 case([[1, 2], 100], None)]
        result = evaluate_callable(two_sum, cases, problem_id="two-sum")
        self.assertEqual(result.total, 3)
        self.assertEqual(result.passed_count, 1)
        self.assertTrue(result.results[0].passed)
        self.assertFalse(result.results[1].passed)
        self.assertFalse(result.results[2].passed)
        self.assertIn("ValueError", result.results[2].error)

    def test_structured_result_to_dict(self):
        result = evaluate_callable(fibonacci, [case([10], 55)], problem_id="fibonacci")
        data = result.to_dict()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["passed"], 1)
        self.assertTrue(data["all_passed"])
        self.assertEqual(data["results"][0]["actual"], 55)


class TestEvaluateCode(unittest.TestCase):
    def test_code_string_passes(self):
        code = "def solve(nums, target):\n    return [0, 1] if nums[0] + nums[1] == target else []\n"
        result = evaluate_code(code, [case([[2, 7], 9], [0, 1])], problem_id="two-sum")
        self.assertTrue(result.all_passed)

    def test_code_string_exception_captured(self):
        code = "def solve(n):\n    raise RuntimeError('boom')\n"
        result = evaluate_code(code, [case([5], 5)], problem_id="fibonacci")
        self.assertFalse(result.results[0].passed)
        self.assertIn("RuntimeError", result.results[0].error)

    def test_code_string_timeout(self):
        code = "def solve(n):\n    while True:\n        pass\n"
        result = evaluate_code(code, [case([5], 5)], problem_id="fibonacci", timeout=1.0)
        self.assertTrue(result.results[0].timed_out)
        self.assertFalse(result.results[0].passed)

    def test_code_string_missing_solve_is_an_error(self):
        result = evaluate_code("x = 1\n", [case([5], 5)])
        self.assertFalse(result.results[0].passed)
        self.assertIn("solve", result.results[0].error)

    def test_evaluate_dispatches_on_type(self):
        self.assertTrue(evaluate(fibonacci, [case([6], 8)]).all_passed)
        self.assertTrue(evaluate("def solve(n):\n    return n * 2\n",
                                 [case([3], 6)]).all_passed)
        with self.assertRaises(TypeError):
            evaluate(123, [case([1], 1)])


if __name__ == "__main__":
    unittest.main()
