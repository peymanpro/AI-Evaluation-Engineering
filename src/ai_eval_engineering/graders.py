"""Deterministic graders for AI-system behavior."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .domain import EvaluationCase, GraderResult, SystemOutput


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.strip().split()).casefold()
    return value


class ExactMatchGrader:
    """Compare expected and actual values without external calls."""

    budget_cost_free = True

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

    budget_cost_free = True

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

    budget_cost_free = True

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

    budget_cost_free = True

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


class SchemaGrader:
    """Small deterministic JSON-schema subset: type, required, and properties."""

    budget_cost_free = True

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
    """Evaluate caller-supplied predicates; their cost behavior is caller-dependent."""

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
    """Grade tool traces and step limits without making external calls."""

    budget_cost_free = True

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
