"""Provider-neutral model-judge boundary and human calibration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from .domain import EvaluationCase, JsonObject, SystemOutput


@dataclass(frozen=True)
class RubricDimension:
    name: str
    description: str
    weight: float = 1.0


@dataclass(frozen=True)
class EvaluationRubric:
    name: str
    dimensions: tuple[RubricDimension, ...]


@dataclass(frozen=True)
class JudgeResult:
    label: str
    score: float
    rationale: str
    dimension_scores: JsonObject


class Judge(Protocol):
    def judge(
        self,
        case: EvaluationCase,
        output: SystemOutput,
        rubric: EvaluationRubric,
    ) -> JudgeResult:
        ...


def validate_judge_result(result: JudgeResult, rubric: EvaluationRubric) -> None:
    if not result.label.strip():
        raise ValueError("Judge label must not be empty.")
    if not math.isfinite(result.score) or not 0.0 <= result.score <= 1.0:
        raise ValueError("Judge score must be finite and within [0, 1].")
    required = {dimension.name for dimension in rubric.dimensions}
    if set(result.dimension_scores) != required:
        raise ValueError("Judge dimension scores must match the rubric exactly.")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
        for value in result.dimension_scores.values()
    ):
        raise ValueError("Judge dimension scores must be finite numbers within [0, 1].")


class FakeJudge:
    """Deterministic fixture standing in for a real provider-backed judge."""

    def __init__(self, labels: dict[str, tuple[str, float]]) -> None:
        self.labels = dict(labels)

    def judge(
        self,
        case: EvaluationCase,
        output: SystemOutput,
        rubric: EvaluationRubric,
    ) -> JudgeResult:
        label, score = self.labels.get(case.id, ("fail", 0.0))
        return JudgeResult(
            label=label,
            score=score,
            rationale="deterministic fixture judge; replace with a validated model adapter",
            dimension_scores={dimension.name: score for dimension in rubric.dimensions},
        )


@dataclass(frozen=True)
class CalibrationReport:
    total: int
    agreement_rate: float
    confusion_matrix: dict[str, dict[str, int]]
    disagreements: tuple[str, ...]

    @property
    def disagreements_count(self) -> int:
        return len(self.disagreements)


def calibrate_judge(
    cases: list[EvaluationCase],
    judge: Judge,
    outputs: dict[str, SystemOutput],
    human_labels: dict[str, str],
    rubric: EvaluationRubric,
) -> CalibrationReport:
    labels = set(human_labels.values())
    confusion = {actual: {pred: 0 for pred in labels} for actual in labels}
    disagreements: list[str] = []
    for case in cases:
        if case.id not in human_labels or case.id not in outputs:
            raise ValueError(f"Missing calibration data for case {case.id}")
        result = judge.judge(case, outputs[case.id], rubric)
        validate_judge_result(result, rubric)
        actual = human_labels[case.id]
        confusion.setdefault(actual, {})
        confusion[actual][result.label] = confusion[actual].get(result.label, 0) + 1
        if result.label != actual:
            disagreements.append(case.id)
    total = len(cases)
    agreement = (total - len(disagreements)) / total if total else 0.0
    return CalibrationReport(total, agreement, confusion, tuple(disagreements))
