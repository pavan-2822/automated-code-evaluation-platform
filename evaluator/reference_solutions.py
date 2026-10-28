"""Small, reviewed reference solutions for the sample problems.

These are deliberately simple, deterministic problems used only to
demonstrate the dispatcher and evaluator. They are not a claim about
any production evaluation platform. Each function is exercised by
independent edge-case assertions in ``tests/test_evaluator.py`` -- the
tests do not merely compare a function with itself.
"""

from __future__ import annotations


def two_sum(nums, target):
    """Return indices ``[i, j]`` with ``nums[i] + nums[j] == target``.

    Each element may be used at most once. Raises ``ValueError`` when
    no such pair exists, instead of silently returning a wrong answer.
    """
    seen = {}
    for i, value in enumerate(nums):
        complement = target - value
        if complement in seen:
            return [seen[complement], i]
        seen[value] = i
    raise ValueError("no two-sum pair exists")


def sorted_squares(nums):
    """Return the squares of ``nums`` sorted in non-decreasing order."""
    return sorted(value * value for value in nums)


def fibonacci(n):
    """Return the ``n``-th Fibonacci number (``fibonacci(0) == 0``)."""
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError("n must be an integer")
    if n < 0:
        raise ValueError("n must be non-negative")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def valid_parentheses(text):
    """Return True when every bracket in ``text`` is correctly closed."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for char in text:
        if char in "([{":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False
    return not stack


# Problem id -> reference implementation. Dispatch looks solutions up
# here, so an unknown problem id fails loudly instead of guessing.
PROBLEM_SOLUTIONS = {
    "two-sum": two_sum,
    "sorted-squares": sorted_squares,
    "fibonacci": fibonacci,
    "valid-parentheses": valid_parentheses,
}


def get_solution(problem_id):
    """Return the reference solution for ``problem_id``.

    Raises ``KeyError`` for unknown ids. Callers that need a friendlier
    error should catch it at the boundary (see ``dispatcher.dispatch``).
    """
    try:
        return PROBLEM_SOLUTIONS[problem_id]
    except KeyError:
        known = ", ".join(sorted(PROBLEM_SOLUTIONS))
        raise KeyError(f"unknown problem id {problem_id!r}; known ids: {known}")
