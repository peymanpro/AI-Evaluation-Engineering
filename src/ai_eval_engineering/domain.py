"""Typed domain contracts for evaluation data and run manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    input: JsonObject
    expected: Any = None
    metadata: JsonObject = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    risk_category: str | None = None


@dataclass(frozen=True)
class SystemOutput:
    case_id: str
    output: Any
    latency_ms: float | None = None
    cost_usd: float | None = None
    trace: list[JsonObject] = field(default_factory=list)


@dataclass(frozen=True)
class GraderResult:
    grader: str
    passed: bool
    score: float
    details: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class CaseResult:
    case: EvaluationCase
    output: SystemOutput
    graders: tuple[GraderResult, ...]


@dataclass(frozen=True)
class RunMetadata:
    run_id: str
    suite_version: str
    system_name: str
    system_version: str
    configuration: JsonObject
    seed: int | None
    timestamp_utc: str
    environment: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationRun:
    manifest: RunMetadata
    cases: tuple[CaseResult, ...]


@dataclass(frozen=True)
class EvaluationSuite:
    version: str
    cases: tuple[EvaluationCase, ...]


@dataclass(frozen=True)
class AggregatedResult:
    total_cases: int
    passed_cases: int
    pass_rate: float
    mean_score: float
    scores: tuple[float, ...]

    @classmethod
    def from_case_results(cls, results: list[CaseResult]) -> AggregatedResult:
        scores = tuple(
            sum(grader.score for grader in result.graders) / len(result.graders)
            if result.graders
            else 0.0
            for result in results
        )
        passed = sum(
            all(grader.passed for grader in result.graders)
            for result in results
        )
        total = len(results)
        return cls(
            total_cases=total,
            passed_cases=passed,
            pass_rate=passed / total if total else 0.0,
            mean_score=sum(scores) / len(scores) if scores else 0.0,
            scores=scores,
        )


def to_json_object(value: Any) -> JsonObject:
    return asdict(value)
