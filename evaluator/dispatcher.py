"""Auto-detecting input dispatcher for evaluation submissions.

The dispatcher detects a submission's shape, normalises every case to
a ``Case`` (inputs as a list, one expected value, raw source, detected
shape), and can route cases to a reference solution by problem id.

Supported shapes, in precedence order (highest first):
1. ``json-object`` -- one JSON object with ``input``/``inputs`` and ``expected``.
2. ``json-list`` -- a JSON list of such case objects.
3. ``jsonl`` -- one JSON case object per line.
4. ``csv`` -- a header row naming ``input`` (or ``inputs``) and ``expected``.
5. ``key-value`` -- ``input=...`` / ``expected=...`` pairs, newline- or
   semicolon-separated (``inputs=...`` may hold a JSON list).
6. ``plain-lines`` -- all but the last non-empty line are inputs, the
   last line is the expected value; each line is coerced (``[2, 7]`` to
   a list, ``9`` to an int, otherwise a string). Example::

       [2, 7, 11, 15]
       9
       [0, 1]

Precedence resolves overlaps: text that parses as JSON and could also
be read as plain lines is JSON, because JSON is the more specific
claim; the detected shape is always returned on the ``Case``.

``input`` means one argument (even if that argument is itself a list);
``inputs`` means a JSON list of arguments. Supplying both for one case
is ambiguous and raises ``AmbiguousInput``.

The dispatcher never guesses silently. ``AmbiguousInput`` is raised
when a document genuinely matches two shapes with no precedence rule
to separate them (a lone ``input=hello`` line, a comma row of
``key=value`` pairs with no input/expected keys, or both ``input``
and ``inputs`` keys). ``MalformedInput`` is raised when a shape is
claimed but broken: invalid JSON, a case without ``expected``, a CSV
row with the wrong column count, or plain lines with fewer than two
lines.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass

from .evaluator import evaluate_callable
from .reference_solutions import get_solution

JSON_OBJECT = "json-object"
JSON_LIST = "json-list"
JSONL = "jsonl"
CSV = "csv"
KEY_VALUE = "key-value"
PLAIN_LINES = "plain-lines"

SHAPES = (JSON_OBJECT, JSON_LIST, JSONL, CSV, KEY_VALUE, PLAIN_LINES)


class MalformedInput(ValueError):
    """Input claimed a shape but did not satisfy it."""


class AmbiguousInput(ValueError):
    """Input matched two shapes and precedence cannot separate them."""


@dataclass
class Case:
    """One normalised evaluation case."""

    inputs: list
    expected: object
    raw: str
    shape: str


@dataclass
class DispatchOutcome:
    """One case plus the reference solution's answer for it."""

    case: Case
    actual: object = None
    passed: bool = False
    error: str | None = None


def _coerce(value):
    """Coerce a string cell to int, float, bool, None, JSON, or string."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    if text[0] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    literals = {"true": True, "True": True, "false": False,
                "False": False, "null": None, "None": None}
    if text in literals:
        return literals[text]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except ValueError:
            pass
    return text


def _case_from_mapping(mapping, raw, shape):
    """Build a Case from a mapping with input/inputs + expected keys."""
    if not isinstance(mapping, dict):
        raise MalformedInput(f"case is not an object: {raw!r}")
    if "input" in mapping and "inputs" in mapping:
        raise AmbiguousInput(
            "case has both 'input' and 'inputs'; cannot tell which is authoritative"
        )
    if "expected" not in mapping:
        raise MalformedInput(f"case is missing 'expected': {raw!r}")
    if "inputs" in mapping:
        inputs = mapping["inputs"]
        if not isinstance(inputs, list):
            raise MalformedInput(f"'inputs' must be a list: {raw!r}")
    elif "input" in mapping:
        inputs = [mapping["input"]]
    else:
        raise MalformedInput(f"case is missing 'input'/'inputs': {raw!r}")
    return Case(inputs=list(inputs), expected=mapping["expected"],
                raw=raw, shape=shape)


def _parse_json_object(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedInput(f"invalid JSON object: {exc}") from exc
    return [_case_from_mapping(data, text, JSON_OBJECT)]


def _parse_json_list(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedInput(f"invalid JSON list: {exc}") from exc
    if not isinstance(data, list):
        raise MalformedInput("JSON list shape requires a top-level list")
    if not data:
        raise MalformedInput("JSON list is empty; at least one case is required")
    return [_case_from_mapping(item, json.dumps(item), JSON_LIST) for item in data]


def _parse_jsonl(text):
    cases = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MalformedInput(f"invalid JSONL line {line!r}: {exc}") from exc
        cases.append(_case_from_mapping(data, line, JSONL))
    if not cases:
        raise MalformedInput("JSONL input has no cases")
    return cases


def _parse_csv(text):
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise MalformedInput(f"invalid CSV: {exc}") from exc
    if len(rows) < 2:
        raise MalformedInput("CSV needs a header row and at least one data row")
    header = [cell.strip() for cell in rows[0]]
    if "input" in header and "inputs" in header:
        raise AmbiguousInput("CSV header has both 'input' and 'inputs' columns")
    if "expected" not in header:
        raise MalformedInput("CSV header must name an 'expected' column")
    if "input" not in header and "inputs" not in header:
        raise MalformedInput("CSV header must name an 'input' or 'inputs' column")
    cases = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            raise MalformedInput(
                f"CSV row has {len(row)} columns, header has {len(header)}: {row!r}"
            )
        record = {key: _coerce(value) for key, value in zip(header, row)}
        cases.append(_case_from_mapping(record, ",".join(row), CSV))
    if not cases:
        raise MalformedInput("CSV has a header but no data rows")
    return cases


def _parse_key_value(text):
    if "\n" in text.strip():
        tokens = [line.strip() for line in text.splitlines() if line.strip()]
    else:
        tokens = [token.strip() for token in text.split(";") if token.strip()]
    pairs = {}
    for token in tokens:
        if "=" not in token:
            raise MalformedInput(f"key-value token has no '=': {token!r}")
        key, _, value = token.partition("=")
        pairs[key.strip()] = _coerce(value.strip())
    # _case_from_mapping enforces both-keys/missing-key rules once.
    return [_case_from_mapping(pairs, text, KEY_VALUE)]


def _parse_plain_lines(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise MalformedInput(
            "plain-lines input needs at least two lines: input(s), then expected"
        )
    inputs = [_coerce(line) for line in lines[:-1]]
    return [Case(inputs=inputs, expected=_coerce(lines[-1]),
                 raw=text, shape=PLAIN_LINES)]


def _is_jsonl(text):
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    for line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict) or "expected" not in data:
            return False
    return True


def _has_csv_header(text):
    first = text.splitlines()[0] if text.splitlines() else ""
    columns = {cell.strip() for cell in first.split(",")}
    return "expected" in columns and ("input" in columns or "inputs" in columns)


def _has_complete_key_value(text):
    if "\n" in text.strip():
        tokens = [line.strip() for line in text.splitlines() if line.strip()]
    else:
        tokens = [token.strip() for token in text.split(";") if token.strip()]
    keys = set()
    for token in tokens:
        if "=" in token:
            keys.add(token.partition("=")[0].strip())
    return "expected" in keys and ("input" in keys or "inputs" in keys)


def detect_shape(text):
    """Detect the shape of ``text`` by the documented precedence order.

    Raises ``MalformedInput`` or ``AmbiguousInput`` instead of
    guessing. JSON shapes are tried first, so JSON text that could
    also be read as plain lines is JSON by precedence.
    """
    if text is None or not str(text).strip():
        raise MalformedInput("input is empty")
    stripped = str(text).strip()
    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            lines = [ln for ln in stripped.splitlines() if ln.strip()]
            # Valid JSONL is not broken JSON. A single JSON-looking
            # line, or all-JSON-object lines with a broken line, is.
            # Anything else (plain lines starting with a JSON list) falls through.
            if _is_jsonl(stripped):
                return JSONL
            if len(lines) == 1 or all(ln.strip().startswith("{") for ln in lines):
                raise MalformedInput(f"invalid JSON: {exc}") from exc
        else:
            if isinstance(data, dict):
                return JSON_OBJECT
            if isinstance(data, list):
                return JSON_LIST
            raise MalformedInput("top-level JSON must be an object or a list of cases")
    if _is_jsonl(stripped):
        return JSONL
    if stripped.splitlines()[0].strip().startswith("{"):
        raise MalformedInput("first line looks like JSON but is not a valid case")
    if _has_csv_header(stripped):
        return CSV
    if _has_complete_key_value(stripped):
        return KEY_VALUE
    # Ambiguity checks: these documents match two shapes at once.
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    keys = {line.partition("=")[0].strip() for line in lines if "=" in line}
    if keys & {"input", "inputs", "expected"}:
        raise AmbiguousInput(
            "incomplete 'input='/'expected=' keys could be a key-value case or "
            "plain input text; supply both keys or use another shape"
        )
    if "=" in stripped and "," in stripped:
        raise AmbiguousInput(
            "text contains both '=' and ',' with no input/expected keys; "
            "it could be a CSV row or a key-value row"
        )
    return PLAIN_LINES


_PARSERS = {
    JSON_OBJECT: _parse_json_object,
    JSON_LIST: _parse_json_list,
    JSONL: _parse_jsonl,
    CSV: _parse_csv,
    KEY_VALUE: _parse_key_value,
    PLAIN_LINES: _parse_plain_lines,
}


def parse_cases(text):
    """Detect the shape of ``text`` and return a normalised Case list."""
    shape = detect_shape(text)
    return _PARSERS[shape](str(text).strip())


def dispatch(problem_id, text):
    """Parse ``text`` and run the reference solution for ``problem_id``.

    Returns a list of ``DispatchOutcome`` (one per case). Unknown
    problem ids raise ``KeyError`` from the solution registry; bad
    input raises ``MalformedInput``/``AmbiguousInput`` before any
    solution runs.
    """
    solution = get_solution(problem_id)
    cases = parse_cases(text)
    result = evaluate_callable(solution, cases, problem_id=problem_id)
    outcomes = []
    for case, case_result in zip(cases, result.results):
        outcomes.append(DispatchOutcome(
            case=case, actual=case_result.actual,
            passed=case_result.passed, error=case_result.error,
        ))
    return outcomes
