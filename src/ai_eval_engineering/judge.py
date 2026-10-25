"""Provider-neutral model-judge boundary and human calibration."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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
    """Validate a judge result's shape and numeric bounds before using it."""
    if not isinstance(result, JudgeResult):
        raise TypeError("result must be a JudgeResult.")
    _validate_rubric(rubric)

    if not isinstance(result.label, str):
        raise TypeError("Judge label must be a string.")
    if not result.label.strip():
        raise ValueError("Judge label must not be empty.")
    if not isinstance(result.rationale, str):
        raise TypeError("Judge rationale must be a string.")
    if isinstance(result.score, bool) or not isinstance(result.score, (int, float)):
        raise TypeError("Judge score must be numeric.")
    try:
        score = float(result.score)
    except OverflowError as exc:
        raise ValueError("Judge score must be finite and within [0, 1].") from exc
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("Judge score must be finite and within [0, 1].")
    if not isinstance(result.dimension_scores, dict):
        raise TypeError("Judge dimension_scores must be a dictionary.")

    required = {dimension.name for dimension in rubric.dimensions}
    if set(result.dimension_scores) != required:
        raise ValueError("Judge dimension scores must match the rubric exactly.")
    for name, value in result.dimension_scores.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"Judge dimension score {name!r} must be numeric.")
        try:
            numeric_value = float(value)
        except OverflowError as exc:
            raise ValueError(
                f"Judge dimension score {name!r} must be finite and within [0, 1]."
            ) from exc
        if not math.isfinite(numeric_value) or not 0.0 <= numeric_value <= 1.0:
            raise ValueError(
                f"Judge dimension score {name!r} must be finite and within [0, 1]."
            )


def _validate_rubric(rubric: EvaluationRubric) -> None:
    if not isinstance(rubric, EvaluationRubric):
        raise TypeError("rubric must be an EvaluationRubric.")
    if not isinstance(rubric.name, str) or not rubric.name.strip():
        raise ValueError("Rubric name must not be empty.")
    if not rubric.dimensions:
        raise ValueError("Rubric must contain at least one dimension.")
    names: list[str] = []
    for dimension in rubric.dimensions:
        if not isinstance(dimension, RubricDimension):
            raise TypeError("Rubric dimensions must be RubricDimension instances.")
        if not isinstance(dimension.name, str):
            raise TypeError("Rubric dimension name must be a string.")
        if not dimension.name.strip():
            raise ValueError("Rubric dimension name must not be empty.")
        if not isinstance(dimension.description, str):
            raise TypeError("Rubric dimension description must be a string.")
        if not dimension.description.strip():
            raise ValueError("Rubric dimension description must not be empty.")
        names.append(dimension.name)
    if len(names) != len(set(names)):
        raise ValueError("Rubric dimension names must be unique.")


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
class LabelCalibration:
    """Per-label confusion statistics relative to human reference labels."""

    label: str
    support: int
    predicted_count: int
    true_positives: int
    precision: float | None
    recall: float | None
    f1: float | None


@dataclass(frozen=True)
class CalibrationReport:
    total: int
    agreement_rate: float
    confusion_matrix: dict[str, dict[str, int]]
    disagreements: tuple[str, ...]
    balanced_accuracy: float | None = None
    macro_precision: float | None = None
    macro_recall: float | None = None
    macro_f1: float | None = None
    cohen_kappa: float | None = None
    per_label_metrics: dict[str, LabelCalibration] = field(default_factory=dict)

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
    """Compare judge labels against human labels and summarize class imbalance.

    The supplied cases define the calibration sample. Outputs and human labels
    must cover exactly those unique case IDs. Macro metrics are averaged across
    labels present in the human reference set; undefined per-label precision
    is counted as zero in macro precision. Cohen's kappa is None when its
    expected-agreement denominator is zero.
    """
    _validate_rubric(rubric)
    if not cases:
        raise ValueError("At least one calibration case is required.")

    case_ids: list[str] = []
    for case in cases:
        if not isinstance(case.id, str) or not case.id.strip():
            raise ValueError("Calibration cases must have non-empty string IDs.")
        case_ids.append(case.id)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Calibration cases must have unique IDs.")

    expected_ids = set(case_ids)
    if any(not isinstance(case_id, str) for case_id in outputs):
        raise TypeError("Output mapping keys must be strings.")
    if any(not isinstance(case_id, str) for case_id in human_labels):
        raise TypeError("Human-label mapping keys must be strings.")
    if set(outputs) != expected_ids:
        missing = sorted(expected_ids - set(outputs))
        extra = sorted(set(outputs) - expected_ids)
        details = []
        if missing:
            details.append("missing outputs: " + ", ".join(missing))
        if extra:
            details.append("unexpected outputs: " + ", ".join(extra))
        raise ValueError("Calibration outputs must match case IDs exactly (" + "; ".join(details) + ").")
    if set(human_labels) != expected_ids:
        missing = sorted(expected_ids - set(human_labels))
        extra = sorted(set(human_labels) - expected_ids)
        details = []
        if missing:
            details.append("missing human labels: " + ", ".join(missing))
        if extra:
            details.append("unexpected human labels: " + ", ".join(extra))
        raise ValueError(
            "Human labels must match case IDs exactly (" + "; ".join(details) + ")."
        )

    for case_id, label in human_labels.items():
        if not isinstance(label, str):
            raise TypeError(f"Human label for case {case_id!r} must be a string.")
        if not label.strip():
            raise ValueError(f"Human label for case {case_id!r} must not be empty.")
        if label != label.strip():
            raise ValueError(
                f"Human label for case {case_id!r} must not contain surrounding whitespace."
            )
    for case_id, output in outputs.items():
        if not isinstance(output, SystemOutput):
            raise TypeError(f"Output for case {case_id!r} must be a SystemOutput.")
        if output.case_id != case_id:
            raise ValueError(
                f"Output case id {output.case_id!r} does not match mapping key {case_id!r}."
            )

    predictions: dict[str, str] = {}
    disagreements: list[str] = []
    for case in cases:
        result = judge.judge(case, outputs[case.id], rubric)
        validate_judge_result(result, rubric)
        predictions[case.id] = result.label
        if result.label != human_labels[case.id]:
            disagreements.append(case.id)

    reference_labels = sorted(set(human_labels.values()))
    all_labels = sorted(set(reference_labels) | set(predictions.values()))
    confusion = {
        actual: {predicted: 0 for predicted in all_labels}
        for actual in all_labels
    }
    for case_id in case_ids:
        actual = human_labels[case_id]
        predicted = predictions[case_id]
        confusion[actual][predicted] += 1

    per_label: dict[str, LabelCalibration] = {}
    for label in all_labels:
        support = sum(confusion[label].values())
        predicted_count = sum(confusion[actual][label] for actual in all_labels)
        true_positives = confusion[label][label]
        precision = true_positives / predicted_count if predicted_count else None
        recall = true_positives / support if support else None
        if support == 0:
            f1 = None
        else:
            f1_denominator = support + predicted_count
            f1 = 2 * true_positives / f1_denominator if f1_denominator else 0.0
        per_label[label] = LabelCalibration(
            label=label,
            support=support,
            predicted_count=predicted_count,
            true_positives=true_positives,
            precision=precision,
            recall=recall,
            f1=f1,
        )

    macro_precision = sum(
        (per_label[label].precision or 0.0) for label in reference_labels
    ) / len(reference_labels)
    macro_recall = sum(
        per_label[label].recall or 0.0 for label in reference_labels
    ) / len(reference_labels)
    macro_f1 = sum(
        per_label[label].f1 or 0.0 for label in reference_labels
    ) / len(reference_labels)

    total = len(case_ids)
    agreement = (total - len(disagreements)) / total
    row_totals = {label: sum(confusion[label].values()) for label in all_labels}
    column_totals = {
        label: sum(confusion[actual][label] for actual in all_labels)
        for label in all_labels
    }
    expected_agreement = sum(
        row_totals[label] * column_totals[label] for label in all_labels
    ) / (total * total)
    kappa_denominator = 1.0 - expected_agreement
    cohen_kappa = (
        (agreement - expected_agreement) / kappa_denominator
        if not math.isclose(kappa_denominator, 0.0, abs_tol=1e-15)
        else None
    )

    return CalibrationReport(
        total=total,
        agreement_rate=agreement,
        confusion_matrix=confusion,
        disagreements=tuple(disagreements),
        balanced_accuracy=macro_recall,
        macro_precision=macro_precision,
        macro_recall=macro_recall,
        macro_f1=macro_f1,
        cohen_kappa=cohen_kappa,
        per_label_metrics=per_label,
    )
