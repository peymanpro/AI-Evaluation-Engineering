import pytest

from ai_eval_engineering.domain import EvaluationCase, SystemOutput
from ai_eval_engineering.judge import (
    EvaluationRubric,
    FakeJudge,
    JudgeResult,
    RubricDimension,
    calibrate_judge,
    validate_judge_result,
)


def rubric() -> EvaluationRubric:
    return EvaluationRubric(
        "quality",
        (RubricDimension("correctness", "matches target"),),
    )


def test_judge_calibration_records_disagreements() -> None:
    cases = [
        EvaluationCase("a", {}, expected="yes"),
        EvaluationCase("b", {}, expected="yes"),
        EvaluationCase("c", {}, expected="no"),
    ]
    outputs = {case.id: SystemOutput(case.id, "x") for case in cases}
    judge = FakeJudge({"a": ("pass", 1.0), "b": ("fail", 0.2), "c": ("fail", 0.0)})
    report = calibrate_judge(
        cases,
        judge,
        outputs,
        {"a": "pass", "b": "pass", "c": "fail"},
        rubric(),
    )
    assert report.total == 3
    assert report.agreement_rate == pytest.approx(2 / 3)
    assert report.disagreements == ("b",)
    assert report.balanced_accuracy == pytest.approx(0.75)
    assert report.macro_precision == pytest.approx(0.75)
    assert report.macro_recall == pytest.approx(0.75)
    assert report.macro_f1 == pytest.approx(2 / 3)
    assert report.cohen_kappa == pytest.approx(0.4)
    assert report.per_label_metrics["pass"].support == 2
    assert report.per_label_metrics["pass"].predicted_count == 1
    assert report.per_label_metrics["pass"].precision == pytest.approx(1.0)
    assert report.per_label_metrics["pass"].recall == pytest.approx(0.5)
    assert report.per_label_metrics["fail"].precision == pytest.approx(0.5)


def test_balanced_accuracy_exposes_majority_class_collapse() -> None:
    cases = [
        EvaluationCase(f"pass-{index}", {}, expected="yes") for index in range(9)
    ] + [EvaluationCase("fail-0", {}, expected="no")]
    outputs = {case.id: SystemOutput(case.id, "x") for case in cases}
    labels = {
        case.id: ("pass" if case.id.startswith("pass-") else "fail")
        for case in cases
    }
    judge = FakeJudge({case.id: ("pass", 0.9) for case in cases})

    report = calibrate_judge(cases, judge, outputs, labels, rubric())

    assert report.agreement_rate == pytest.approx(0.9)
    assert report.balanced_accuracy == pytest.approx(0.5)
    assert report.cohen_kappa == pytest.approx(0.0)
    assert report.per_label_metrics["fail"].recall == pytest.approx(0.0)
    assert report.per_label_metrics["fail"].precision is None
    assert report.per_label_metrics["fail"].f1 == pytest.approx(0.0)


def test_unknown_judge_label_is_visible_in_confusion_matrix() -> None:
    cases = [
        EvaluationCase("a", {}, expected="yes"),
        EvaluationCase("b", {}, expected="no"),
    ]
    outputs = {case.id: SystemOutput(case.id, "x") for case in cases}
    judge = FakeJudge({"a": ("unknown", 0.2), "b": ("fail", 0.8)})

    report = calibrate_judge(
        cases, judge, outputs, {"a": "pass", "b": "fail"}, rubric()
    )

    assert "unknown" in report.confusion_matrix
    assert report.confusion_matrix["pass"]["unknown"] == 1
    assert report.per_label_metrics["unknown"].support == 0
    assert report.per_label_metrics["unknown"].precision == pytest.approx(0.0)
    assert report.per_label_metrics["unknown"].recall is None


def test_perfect_single_class_calibration_has_undefined_kappa() -> None:
    cases = [
        EvaluationCase("a", {}, expected="yes"),
        EvaluationCase("b", {}, expected="yes"),
    ]
    outputs = {case.id: SystemOutput(case.id, "x") for case in cases}
    judge = FakeJudge({"a": ("pass", 0.9), "b": ("pass", 0.9)})

    report = calibrate_judge(
        cases, judge, outputs, {"a": "pass", "b": "pass"}, rubric()
    )

    assert report.agreement_rate == 1.0
    assert report.cohen_kappa is None


def test_calibration_requires_nonempty_unique_cases_and_exact_input_maps() -> None:
    judge = FakeJudge({})
    with pytest.raises(ValueError, match="At least one"):
        calibrate_judge([], judge, {}, {}, rubric())

    duplicate_cases = [
        EvaluationCase("a", {}, expected="yes"),
        EvaluationCase("a", {}, expected="no"),
    ]
    with pytest.raises(ValueError, match="unique IDs"):
        calibrate_judge(
            duplicate_cases,
            judge,
            {"a": SystemOutput("a", "x")},
            {"a": "pass"},
            rubric(),
        )

    case = EvaluationCase("a", {}, expected="yes")
    with pytest.raises(ValueError, match="outputs must match"):
        calibrate_judge([case], judge, {}, {"a": "pass"}, rubric())

    with pytest.raises(ValueError, match="Human labels must match"):
        calibrate_judge(
            [case],
            judge,
            {"a": SystemOutput("a", "x")},
            {},
            rubric(),
        )


def test_calibration_rejects_output_id_mismatch_and_empty_reference_label() -> None:
    case = EvaluationCase("a", {}, expected="yes")
    with pytest.raises(ValueError, match="does not match mapping key"):
        calibrate_judge(
            [case],
            FakeJudge({}),
            {"a": SystemOutput("wrong", "x")},
            {"a": "pass"},
            rubric(),
        )

    with pytest.raises(ValueError, match="must not be empty"):
        calibrate_judge(
            [case],
            FakeJudge({}),
            {"a": SystemOutput("a", "x")},
            {"a": "   "},
            rubric(),
        )


def test_invalid_judge_output_is_rejected() -> None:
    invalid = JudgeResult("pass", 1.5, "bad", {"correctness": 1.0})
    with pytest.raises(ValueError, match="within"):
        validate_judge_result(invalid, rubric())


def test_judge_result_numeric_types_are_validated_precisely() -> None:
    with pytest.raises(TypeError, match="score must be numeric"):
        validate_judge_result(
            JudgeResult("pass", True, "invalid", {"correctness": 1.0}),  # type: ignore[arg-type]
            rubric(),
        )
    with pytest.raises(TypeError, match="label must be a string"):
        validate_judge_result(
            JudgeResult(None, 0.5, "invalid", {"correctness": 0.5}),  # type: ignore[arg-type]
            rubric(),
        )


def test_rubric_requires_unique_nonempty_dimensions() -> None:
    invalid = EvaluationRubric(
        "quality",
        (
            RubricDimension("correctness", "first"),
            RubricDimension("correctness", "duplicate"),
        ),
    )
    with pytest.raises(ValueError, match="unique"):
        validate_judge_result(
            JudgeResult("pass", 0.5, "reason", {"correctness": 0.5}), invalid
        )
