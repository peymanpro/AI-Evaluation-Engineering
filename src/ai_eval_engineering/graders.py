"""Deterministic graders for AI-system behavior."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from .contracts import validate_grader_results
from .domain import EvaluationCase, GraderResult, SystemOutput
from .runner import Grader


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.strip().split()).casefold()
    return value


class ExactMatchGrader:
    def __init__(self, name: str = "exact_match", normalize: bool = True) -> None:
        self.name = name
        self.normalize = normalize

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        expected = case.expected
        actual = output.output
        if self.normalize:
            expected = _normalize(expected)
            actual = _normalize(actual)
        passed = actual == expected
        return GraderResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            details="exact match" if passed else f"expected {expected!r}, got {actual!r}",
        )


class ContainsGrader:
    """Check whether a string output contains the case's expected substring."""

    def __init__(
        self,
        name: str = "contains",
        *,
        substring: str | None = None,
        case_sensitive: bool = False,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must not be empty.")
        if substring is not None and (not isinstance(substring, str) or not substring):
            raise ValueError("substring must be a non-empty string or None.")
        if not isinstance(case_sensitive, bool):
            raise TypeError("case_sensitive must be a boolean.")
        self.name = name
        self.substring = substring
        self.case_sensitive = case_sensitive

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        expected = self.substring if self.substring is not None else case.expected
        actual = output.output
        if not isinstance(expected, str) or not isinstance(actual, str):
            return GraderResult(
                grader=self.name,
                passed=False,
                score=0.0,
                details="contains grader requires string expected and actual values",
            )
        if not expected:
            return GraderResult(
                grader=self.name,
                passed=False,
                score=0.0,
                details="expected substring must not be empty",
            )
        left, right = (actual, expected) if self.case_sensitive else (
            actual.casefold(),
            expected.casefold(),
        )
        passed = right in left
        return GraderResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            details="expected substring found" if passed else "expected substring not found",
        )


class RegexGrader:
    """Match string output against the case's expected regular-expression pattern.

    Patterns come from the evaluation case's expected value. Only use trusted
    patterns: Python's regular-expression engine does not impose a time limit.
    """

    def __init__(
        self,
        name: str = "regex",
        *,
        pattern: str | None = None,
        full_match: bool = False,
        case_sensitive: bool = True,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must not be empty.")
        if pattern is not None and (not isinstance(pattern, str) or not pattern):
            raise ValueError("pattern must be a non-empty string or None.")
        if not isinstance(full_match, bool):
            raise TypeError("full_match must be a boolean.")
        if not isinstance(case_sensitive, bool):
            raise TypeError("case_sensitive must be a boolean.")
        self.name = name
        self.pattern = pattern
        self.full_match = full_match
        self.case_sensitive = case_sensitive
        self._compiled_pattern = self._compile(pattern) if pattern is not None else None

    def _compile(self, pattern: str) -> re.Pattern[str]:
        try:
            return re.compile(pattern, 0 if self.case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise ValueError("pattern is not a valid regular-expression pattern.") from exc

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        pattern = self.pattern if self.pattern is not None else case.expected
        actual = output.output
        if not isinstance(pattern, str) or not isinstance(actual, str):
            return GraderResult(
                grader=self.name,
                passed=False,
                score=0.0,
                details="regex grader requires string pattern and actual values",
            )
        if not pattern:
            return GraderResult(
                grader=self.name,
                passed=False,
                score=0.0,
                details="regular-expression pattern must not be empty",
            )
        try:
            compiled = self._compiled_pattern or self._compile(pattern)
        except ValueError:
            return GraderResult(
                grader=self.name,
                passed=False,
                score=0.0,
                details="case expected value is not a valid regular-expression pattern",
            )
        matched = (
            compiled.fullmatch(actual) is not None
            if self.full_match
            else compiled.search(actual) is not None
        )
        return GraderResult(
            grader=self.name,
            passed=matched,
            score=1.0 if matched else 0.0,
            details="regular expression matched" if matched else "regular expression did not match",
        )


class NumericToleranceGrader:
    """Compare numeric output with the expected value using absolute/relative tolerance.

    A result passes when abs(actual - expected) <= abs_tol + rel_tol * abs(expected).
    Scores are binary so the class does not imply a domain-specific error scale.
    """

    def __init__(
        self,
        name: str = "numeric_tolerance",
        *,
        abs_tol: float = 0.0,
        rel_tol: float = 0.0,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must not be empty.")
        self.name = name
        self.abs_tol = _validate_tolerance(abs_tol, "abs_tol")
        self.rel_tol = _validate_tolerance(rel_tol, "rel_tol")

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        expected = _finite_numeric(case.expected)
        actual = _finite_numeric(output.output)
        if expected is None or actual is None:
            return GraderResult(
                grader=self.name,
                passed=False,
                score=0.0,
                details="numeric tolerance grader requires finite numeric expected and actual values",
            )
        difference = abs(actual - expected)
        allowed_error = self.abs_tol + self.rel_tol * abs(expected)
        if not math.isfinite(difference) or not math.isfinite(allowed_error):
            return GraderResult(
                grader=self.name,
                passed=False,
                score=0.0,
                details="numeric tolerance comparison exceeded the finite numeric range",
            )
        passed = difference <= allowed_error
        return GraderResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            details=(
                f"absolute error {difference:.8g} is within tolerance {allowed_error:.8g}"
                if passed
                else f"absolute error {difference:.8g} exceeds tolerance {allowed_error:.8g}"
            ),
            metadata={
                "expected": expected,
                "actual": actual,
                "absolute_error": difference,
                "allowed_error": allowed_error,
            },
        )


def _validate_tolerance(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric.")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite and non-negative.") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{name} must be finite and non-negative.")
    return numeric


def _finite_numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except OverflowError:
        return None
    return numeric if math.isfinite(numeric) else None


_JSON_FIELD_MISSING = object()
_JSON_FIELD_UNSET = object()


class JsonFieldGrader:
    """Compare one JSON output field with the expected value using JSON Pointer.

    The case's expected value is compared with the value at the configured
    pointer unless a fixed expected_value is supplied. Examples: /decision,
    /user/tier, /items/0/id. Field values are compared structurally; numeric
    int/float values compare numerically, while booleans are never treated as
    numbers. The grader does not echo field values into details or metadata.
    """

    def __init__(
        self,
        path: str,
        name: str = "json_field",
        *,
        expected_value: Any = _JSON_FIELD_UNSET,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must not be empty.")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("path must be a non-empty JSON Pointer beginning with '/'.")
        tokens: list[str] = []
        for token in path[1:].split("/"):
            if re.search(r"~(?![01])", token):
                raise ValueError("path contains an invalid JSON Pointer escape.")
            tokens.append(token.replace("~1", "/").replace("~0", "~"))
        if expected_value is not _JSON_FIELD_UNSET and not _is_json_value(expected_value):
            raise ValueError("expected_value must be a finite JSON-compatible value.")
        self.name = name
        self.path = path
        self.expected_value = (
            deepcopy(expected_value)
            if expected_value is not _JSON_FIELD_UNSET
            else _JSON_FIELD_UNSET
        )
        self._tokens = tuple(tokens)

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        actual = _resolve_json_pointer(output.output, self._tokens)
        if actual is _JSON_FIELD_MISSING:
            return GraderResult(
                grader=self.name,
                passed=False,
                score=0.0,
                details="JSON Pointer path was not found in the output",
                metadata={"path": self.path, "field_found": False},
            )
        expected = (
            case.expected
            if self.expected_value is _JSON_FIELD_UNSET
            else self.expected_value
        )
        passed = _json_values_equal(actual, expected)
        return GraderResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            details=(
                "JSON field matches the expected value"
                if passed
                else "JSON field does not match the expected value"
            ),
            metadata={"path": self.path, "field_found": True},
        )


def _resolve_json_pointer(value: Any, tokens: tuple[str, ...]) -> Any:
    current = value
    for token in tokens:
        if isinstance(current, Mapping):
            if token not in current:
                return _JSON_FIELD_MISSING
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (token.startswith("0") and token != "0"):
                return _JSON_FIELD_MISSING
            index = int(token)
            if index >= len(current):
                return _JSON_FIELD_MISSING
            current = current[index]
        else:
            return _JSON_FIELD_MISSING
    return current


def _is_json_value(value: Any, ancestors: set[int] | None = None) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if not isinstance(value, (list, dict)):
        return False
    active = set() if ancestors is None else ancestors
    identity = id(value)
    if identity in active:
        return False
    active.add(identity)
    if isinstance(value, list):
        valid = all(_is_json_value(item, active) for item in value)
    else:
        valid = all(isinstance(key, str) and _is_json_value(item, active) for key, item in value.items())
    active.remove(identity)
    return valid


def _json_values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if isinstance(actual, float) and not math.isfinite(actual):
            return False
        if isinstance(expected, float) and not math.isfinite(expected):
            return False
        return actual == expected
    if actual is None or expected is None:
        return actual is None and expected is None
    if isinstance(actual, str) and isinstance(expected, str):
        return actual == expected
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _json_values_equal(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    if isinstance(actual, Mapping) and isinstance(expected, Mapping):
        if any(not isinstance(key, str) for key in actual) or any(
            not isinstance(key, str) for key in expected
        ):
            return False
        return actual.keys() == expected.keys() and all(
            _json_values_equal(actual[key], expected[key]) for key in actual
        )
    return False


class CompositeGrader:
    """Combine synchronous graders using explicit weights and a pass rule.

    Component scores must be finite and in [0, 1]. The reported score is their
    weighted mean. Pass behavior defaults to all component graders passing;
    callers can instead choose any-pass or a weighted-score threshold.
    """

    def __init__(
        self,
        graders: Iterable[Grader],
        name: str = "composite",
        *,
        weights: Iterable[float] | None = None,
        pass_mode: Literal["all", "any", "score_threshold"] = "all",
        min_score: float = 0.5,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must not be empty.")
        self.graders = tuple(graders)
        if not self.graders:
            raise ValueError("At least one component grader is required.")
        if not all(callable(getattr(grader, "grade", None)) for grader in self.graders):
            raise TypeError("Every component must provide a callable grade method.")
        if pass_mode not in {"all", "any", "score_threshold"}:
            raise ValueError("pass_mode must be 'all', 'any', or 'score_threshold'.")
        threshold = _validate_tolerance(min_score, "min_score")
        if threshold > 1.0:
            raise ValueError("min_score must be between 0 and 1.")
        if weights is None:
            normalized_weights = tuple(1.0 for _ in self.graders)
        else:
            raw_weights = tuple(weights)
            if len(raw_weights) != len(self.graders):
                raise ValueError("weights must contain one value per component grader.")
            normalized: list[float] = []
            for index, value in enumerate(raw_weights):
                weight = _validate_tolerance(value, f"weights[{index}]")
                if weight <= 0:
                    raise ValueError("component weights must be greater than zero.")
                normalized.append(weight)
            normalized_weights = tuple(normalized)
        try:
            total_weight = math.fsum(normalized_weights)
        except OverflowError as exc:
            raise ValueError("sum of component weights must be finite.") from exc
        if not math.isfinite(total_weight) or total_weight <= 0:
            raise ValueError("sum of component weights must be finite and positive.")

        self.name = name
        self.weights = normalized_weights
        self._total_weight = total_weight
        self.pass_mode = pass_mode
        self.min_score = threshold

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        results = tuple(grader.grade(case, output) for grader in self.graders)
        validate_grader_results(results, case.id)
        for result in results:
            score = result.score
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or not 0.0 <= score <= 1.0
            ):
                raise ValueError(
                    f"Component grader {result.grader!r} must return a finite score in [0, 1]."
                )

        score = math.fsum(
            weight * float(result.score)
            for weight, result in zip(self.weights, results, strict=True)
        ) / self._total_weight
        passed_count = sum(result.passed for result in results)
        if self.pass_mode == "all":
            passed = passed_count == len(results)
        elif self.pass_mode == "any":
            passed = passed_count > 0
        else:
            passed = score >= self.min_score

        components = [
            {
                "grader": result.grader,
                "passed": result.passed,
                "score": float(result.score),
                "weight": weight,
            }
            for weight, result in zip(self.weights, results, strict=True)
        ]
        if self.pass_mode == "score_threshold":
            rule = f"weighted score threshold {self.min_score:.6g}"
        else:
            rule = f"{self.pass_mode} component pass rule"
        return GraderResult(
            grader=self.name,
            passed=passed,
            score=score,
            details=(
                f"{passed_count}/{len(results)} component graders passed; "
                f"weighted score {score:.6g}; pass rule: {rule}"
            ),
            metadata={
                "pass_mode": self.pass_mode,
                "min_score": self.min_score,
                "components": components,
            },
        )


class SchemaGrader:
    """Small deterministic JSON-schema subset: type, required, and properties."""

    def __init__(self, schema: Mapping[str, Any], name: str = "schema") -> None:
        self.schema = dict(schema)
        self.name = name

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        ok, details = _validate_schema(output.output, self.schema, "$")
        return GraderResult(
            grader=self.name,
            passed=ok,
            score=1.0 if ok else 0.0,
            details=details,
        )


def _validate_schema(value: Any, schema: Mapping[str, Any], path: str) -> tuple[bool, str]:
    expected_type = schema.get("type")
    if expected_type is not None:
        type_map: dict[str, tuple[type[Any], ...]] = {
            "object": (dict,),
            "array": (list,),
            "string": (str,),
            "number": (int, float),
            "integer": (int,),
            "boolean": (bool,),
            "null": (type(None),),
        }
        allowed = type_map.get(str(expected_type))
        if allowed is None:
            return False, f"{path}: unsupported schema type {expected_type!r}"
        if not isinstance(value, allowed) or (
            expected_type in {"number", "integer"} and isinstance(value, bool)
        ):
            return False, f"{path}: expected {expected_type}"

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list):
            return False, f"{path}: required must be a list"
        for name in required:
            if name not in value:
                return False, f"{path}: missing required field {name!r}"
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return False, f"{path}: properties must be an object"
        for name, child_schema in properties.items():
            if name in value and isinstance(child_schema, dict):
                valid, details = _validate_schema(value[name], child_schema, f"{path}.{name}")
                if not valid:
                    return valid, details
    return True, "schema valid"


@dataclass(frozen=True)
class Rule:
    name: str
    predicate: Callable[[EvaluationCase, SystemOutput], bool]
    failure_message: str


class RuleBasedGrader:
    def __init__(self, rules: Iterable[Rule], name: str = "rules") -> None:
        self.rules = tuple(rules)
        if not self.rules:
            raise ValueError("At least one rule is required.")
        self.name = name

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        failures = [
            rule.failure_message
            for rule in self.rules
            if not rule.predicate(case, output)
        ]
        passed = not failures
        score = (len(self.rules) - len(failures)) / len(self.rules)
        details = "all rules passed" if passed else "; ".join(failures)
        return GraderResult(self.name, passed, score, details)


class TrajectoryGrader:
    def __init__(
        self,
        forbidden_tools: set[str] | None = None,
        required_tools: set[str] | None = None,
        max_steps: int | None = None,
        name: str = "trajectory",
    ) -> None:
        self.forbidden_tools = forbidden_tools or set()
        self.required_tools = required_tools or set()
        self.max_steps = max_steps
        self.name = name

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        tools = [str(event.get("tool_name")) for event in output.trace if event.get("tool_name")]
        failures: list[str] = []
        forbidden = sorted(set(tools) & self.forbidden_tools)
        missing = sorted(self.required_tools - set(tools))
        if forbidden:
            failures.append(f"forbidden tools used: {', '.join(forbidden)}")
        if missing:
            failures.append(f"required tools missing: {', '.join(missing)}")
        if self.max_steps is not None and len(output.trace) > self.max_steps:
            failures.append(f"trajectory has {len(output.trace)} steps; max is {self.max_steps}")
        passed = not failures
        return GraderResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            details="trajectory valid" if passed else "; ".join(failures),
            metadata={"steps": len(output.trace), "tools": tools},
        )
