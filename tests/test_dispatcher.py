"""Tests for the auto-detecting input dispatcher.

Every supported shape, the documented precedence order, the
ambiguity rules, and the malformed-input rules are covered here.
"""

import unittest

from evaluator.dispatcher import (
    AmbiguousInput,
    MalformedInput,
    detect_shape,
    dispatch,
    parse_cases,
)


class TestJsonShapes(unittest.TestCase):
    def test_json_object_single_input(self):
        cases = parse_cases('{"input": 10, "expected": 55}')
        self.assertEqual(cases[0].shape, "json-object")
        self.assertEqual(cases[0].inputs, [10])
        self.assertEqual(cases[0].expected, 55)

    def test_json_object_inputs_list(self):
        cases = parse_cases('{"inputs": [[2, 7, 11, 15], 9], "expected": [0, 1]}')
        self.assertEqual(cases[0].inputs, [[2, 7, 11, 15], 9])
        self.assertEqual(cases[0].expected, [0, 1])

    def test_json_object_extra_key_ignored(self):
        cases = parse_cases('{"input": 10, "expected": 55, "note": "hi"}')
        self.assertEqual(cases[0].expected, 55)

    def test_json_list_of_cases(self):
        text = ('[{"inputs": [[2, 7], 9], "expected": [0, 1]}, '
                '{"input": 5, "expected": 5}]')
        cases = parse_cases(text)
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].shape, "json-list")
        self.assertEqual(cases[1].inputs, [5])

    def test_jsonl_two_cases(self):
        text = ('{"inputs": [[2, 7, 11, 15], 9], "expected": [0, 1]}\n'
                '{"inputs": [[3, 2, 4], 6], "expected": [1, 2]}')
        cases = parse_cases(text)
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].shape, "jsonl")
        self.assertEqual(cases[1].expected, [1, 2])

    def test_json_precedence_over_plain_lines(self):
        # Read as plain lines this would be one line with no expected
        # value; precedence says it is JSON, and it parses as JSON.
        self.assertEqual(detect_shape('{"input": 10, "expected": 55}'), "json-object")

    def test_jsonl_precedence_over_plain_lines(self):
        text = ('{"input": 10, "expected": 55}\n'
                '{"input": 0, "expected": 0}')
        self.assertEqual(detect_shape(text), "jsonl")


class TestCsvAndKeyValue(unittest.TestCase):
    def test_csv_input_and_expected_columns(self):
        text = 'input,expected\n"[-4, -1, 0, 3, 10]","[0, 1, 9, 16, 100]"'
        cases = parse_cases(text)
        self.assertEqual(cases[0].shape, "csv")
        self.assertEqual(cases[0].inputs, [[-4, -1, 0, 3, 10]])
        self.assertEqual(cases[0].expected, [0, 1, 9, 16, 100])

    def test_csv_inputs_column(self):
        text = 'inputs,expected\n"[[2, 7, 11, 15], 9]","[0, 1]"'
        cases = parse_cases(text)
        self.assertEqual(cases[0].inputs, [[2, 7, 11, 15], 9])

    def test_csv_columns_may_appear_in_either_order(self):
        text = "expected,input\n55,10"
        cases = parse_cases(text)
        self.assertEqual(cases[0].inputs, [10])
        self.assertEqual(cases[0].expected, 55)

    def test_csv_trailing_blank_line_skipped(self):
        cases = parse_cases("input,expected\n10,55\n\n")
        self.assertEqual(len(cases), 1)

    def test_key_value_newlines(self):
        cases = parse_cases("input=10\nexpected=55")
        self.assertEqual(cases[0].shape, "key-value")
        self.assertEqual(cases[0].inputs, [10])
        self.assertEqual(cases[0].expected, 55)

    def test_key_value_semicolons(self):
        cases = parse_cases("inputs=[[2, 7, 11, 15], 9]; expected=[0, 1]")
        self.assertEqual(cases[0].inputs, [[2, 7, 11, 15], 9])

    def test_key_value_extra_key_ignored(self):
        cases = parse_cases("input=10\nexpected=55\nnote=hello")
        self.assertEqual(cases[0].expected, 55)


class TestPlainLines(unittest.TestCase):
    def test_plain_single_input(self):
        cases = parse_cases("10\n55")
        self.assertEqual(cases[0].shape, "plain-lines")
        self.assertEqual(cases[0].inputs, [10])
        self.assertEqual(cases[0].expected, 55)

    def test_plain_two_inputs(self):
        cases = parse_cases("[2, 7, 11, 15]\n9\n[0, 1]")
        self.assertEqual(cases[0].inputs, [[2, 7, 11, 15], 9])
        self.assertEqual(cases[0].expected, [0, 1])

    def test_plain_string_input_stays_string(self):
        cases = parse_cases("(())\ntrue")
        self.assertEqual(cases[0].inputs, ["(())"])
        self.assertEqual(cases[0].expected, True)

    def test_plain_scalar_coercion(self):
        cases = parse_cases("42\n-3\n3.5")
        self.assertEqual(cases[0].inputs, [42, -3])
        self.assertEqual(cases[0].expected, 3.5)


class TestAmbiguity(unittest.TestCase):
    def test_both_input_and_inputs_json_is_ambiguous(self):
        with self.assertRaises(AmbiguousInput):
            parse_cases('{"input": 1, "inputs": [1], "expected": 2}')

    def test_both_input_and_inputs_csv_is_ambiguous(self):
        with self.assertRaises(AmbiguousInput):
            parse_cases("input,inputs,expected\n1,[1],2")

    def test_single_input_equals_line_is_ambiguous(self):
        with self.assertRaises(AmbiguousInput):
            parse_cases("input=hello")

    def test_incomplete_key_value_lines_are_ambiguous(self):
        with self.assertRaises(AmbiguousInput):
            parse_cases("input=1\nfoo=2")

    def test_comma_key_value_row_is_ambiguous(self):
        with self.assertRaises(AmbiguousInput):
            parse_cases("a=1,b=2")


class TestMalformed(unittest.TestCase):
    def test_empty_input(self):
        with self.assertRaises(MalformedInput):
            parse_cases("   ")

    def test_invalid_json_single_line(self):
        with self.assertRaises(MalformedInput):
            parse_cases('{"inputs": 1,')

    def test_json_object_missing_expected(self):
        with self.assertRaises(MalformedInput):
            parse_cases('{"input": 10}')

    def test_json_list_empty(self):
        with self.assertRaises(MalformedInput):
            parse_cases("[]")

    def test_jsonl_with_a_broken_line(self):
        with self.assertRaises(MalformedInput):
            parse_cases('{"input": 10, "expected": 55}\n{"input": 1,')

    def test_csv_row_wrong_column_count(self):
        with self.assertRaises(MalformedInput):
            parse_cases("input,expected\n10,55,extra")

    def test_csv_header_missing_expected(self):
        # The CSV parser itself rejects a header without 'expected'.
        # (Through parse_cases, a header-less comma document is not
        # claimed as CSV at all, so it falls through to plain lines.)
        from evaluator.dispatcher import _parse_csv

        with self.assertRaises(MalformedInput):
            _parse_csv("input,other\n10,55")

    def test_plain_single_line_has_no_expected(self):
        with self.assertRaises(MalformedInput):
            parse_cases("hello")


class TestDispatch(unittest.TestCase):
    def test_dispatch_two_sum_passes(self):
        outcomes = dispatch("two-sum", '{"inputs": [[2, 7, 11, 15], 9], "expected": [0, 1]}')
        self.assertTrue(outcomes[0].passed)
        self.assertEqual(outcomes[0].actual, [0, 1])

    def test_dispatch_wrong_expected_fails_without_crashing(self):
        outcomes = dispatch("two-sum", '{"inputs": [[2, 7, 11, 15], 9], "expected": [0, 2]}')
        self.assertFalse(outcomes[0].passed)
        self.assertEqual(outcomes[0].actual, [0, 1])

    def test_dispatch_unknown_problem_raises(self):
        with self.assertRaises(KeyError):
            dispatch("not-a-problem", '{"input": 1, "expected": 1}')

    def test_dispatch_solution_exception_is_captured(self):
        outcomes = dispatch("fibonacci", '{"input": -1, "expected": 0}')
        self.assertFalse(outcomes[0].passed)
        self.assertIsNotNone(outcomes[0].error)
        self.assertIn("ValueError", outcomes[0].error)

    def test_dispatch_plain_lines_fibonacci(self):
        outcomes = dispatch("fibonacci", "10\n55")
        self.assertTrue(outcomes[0].passed)


if __name__ == "__main__":
    unittest.main()
