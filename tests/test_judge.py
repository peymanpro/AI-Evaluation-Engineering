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


def test_judge_calibration_records_disagreements() -> None:
    cases = [
        EvaluationCase("a", {}, expected="yes"),
        EvaluationCase("b", {}, expected="yes"),
        EvaluationCase("c", {}, expected="no"),
    ]
    outputs = {case.id: SystemOutput(case.id, "x") for case in cases}
    judge = FakeJudge({"a": ("pass", 1.0), "b": ("fail", 0.2), "c": ("fail", 0.0)})
    rubric = EvaluationRubric("quality", (RubricDimension("correctness", "matches target"),))
    report = calibrate_judge(
        cases,
        judge,
        outputs,
        {"a": "pass", "b": "pass", "c": "fail"},
        rubric,
    )
    assert report.total == 3
    assert report.agreement_rate == 2 / 3
    assert report.disagreements == ("b",)


def test_invalid_judge_output_is_rejected() -> None:
    rubric = EvaluationRubric("quality", (RubricDimension("correctness", "matches target"),))
    invalid = JudgeResult("pass", 1.5, "bad", {"correctness": 1.0})
    with pytest.raises(ValueError):
        validate_judge_result(invalid, rubric)
