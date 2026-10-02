"""Deterministic graders for AI-system behavior."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .domain import EvaluationCase, GraderResult, SystemOutput


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
