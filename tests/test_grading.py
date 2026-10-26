import pytest

from ai_eval_engineering import ContainsGrader, NumericToleranceGrader, RegexGrader
from ai_eval_engineering.domain import EvaluationCase, SystemOutput
from ai_eval_engineering.graders import ExactMatchGrader, TrajectoryGrader


def test_exact_match_normalizes_text() -> None:
    case = EvaluationCase("a", {}, expected=" Hello   World ")
    output = SystemOutput("a", "hello world")
    assert ExactMatchGrader().grade(case, output).passed


def test_trajectory_grader_detects_forbidden_and_excessive_steps() -> None:
    case = EvaluationCase("a", {}, expected=None)
    output = SystemOutput(
        "a",
        "done",
        trace=[
            {"tool_name": "search"},
            {"tool_name": "delete"},
            {"tool_name": "delete"},
        ],
    )
    result = TrajectoryGrader(forbidden_tools={"delete"}, max_steps=2).grade(case, output)
    assert not result.passed
    assert "forbidden" in result.details
    assert "max is 2" in result.details



def test_contains_grader_checks_expected_substring_case_insensitively() -> None:
    case = EvaluationCase("contains", {}, expected="shipment delayed")
    output = SystemOutput("contains", "Your SHIPMENT DELAYED due to weather")
    result = ContainsGrader().grade(case, output)

    assert result.passed
    assert result.score == 1.0


def test_contains_grader_fails_explicitly_for_non_string_values() -> None:
    case = EvaluationCase("contains", {}, expected=42)
    output = SystemOutput("contains", 42)
    result = ContainsGrader().grade(case, output)

    assert not result.passed
    assert result.score == 0.0
    assert "requires string" in result.details


def test_regex_grader_supports_search_and_full_match() -> None:
    case = EvaluationCase("regex", {}, expected=r"ORD-[0-9]{4}")
    output = SystemOutput("regex", "Your order is ORD-1234.")

    assert RegexGrader().grade(case, output).passed
    assert not RegexGrader(full_match=True).grade(case, output).passed
    assert RegexGrader(full_match=True).grade(
        EvaluationCase("regex-full", {}, expected=r"ORD-[0-9]{4}"),
        SystemOutput("regex-full", "ORD-1234"),
    ).passed


def test_regex_grader_rejects_invalid_pattern_as_a_failed_case() -> None:
    result = RegexGrader().grade(
        EvaluationCase("regex-invalid", {}, expected="["),
        SystemOutput("regex-invalid", "anything"),
    )

    assert not result.passed
    assert "not a valid" in result.details


def test_numeric_tolerance_grader_uses_absolute_and_relative_tolerance() -> None:
    grader = NumericToleranceGrader(abs_tol=0.1, rel_tol=0.01)
    within = grader.grade(
        EvaluationCase("within", {}, expected=100.0),
        SystemOutput("within", 101.0),
    )
    outside = grader.grade(
        EvaluationCase("outside", {}, expected=100.0),
        SystemOutput("outside", 101.2),
    )

    assert within.passed
    assert within.metadata["allowed_error"] == pytest.approx(1.1)
    assert not outside.passed
    assert outside.metadata["absolute_error"] == pytest.approx(1.2)


def test_numeric_tolerance_grader_rejects_bool_and_non_finite_values() -> None:
    grader = NumericToleranceGrader()
    bool_result = grader.grade(
        EvaluationCase("bool", {}, expected=True),
        SystemOutput("bool", 1),
    )
    non_finite_result = grader.grade(
        EvaluationCase("infinite", {}, expected=float("inf")),
        SystemOutput("infinite", float("inf")),
    )

    assert not bool_result.passed
    assert not non_finite_result.passed


def test_numeric_tolerance_configuration_must_be_finite_and_non_negative() -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        NumericToleranceGrader(abs_tol=float("inf"))
    with pytest.raises(ValueError, match="finite and non-negative"):
        NumericToleranceGrader(rel_tol=-0.1)



def test_contains_grader_can_use_a_configured_substring() -> None:
    result = ContainsGrader(substring="approved").grade(
        EvaluationCase("configured-contains", {}, expected=None),
        SystemOutput("configured-contains", "Request approved by policy"),
    )

    assert result.passed


def test_regex_grader_can_use_a_precompiled_configured_pattern() -> None:
    grader = RegexGrader(pattern=r"ORDER-[0-9]{4}", full_match=True)
    result = grader.grade(
        EvaluationCase("configured-regex", {}, expected=None),
        SystemOutput("configured-regex", "ORDER-1234"),
    )

    assert result.passed


def test_regex_grader_rejects_invalid_configured_pattern_at_construction() -> None:
    with pytest.raises(ValueError, match="valid regular-expression"):
        RegexGrader(pattern="[")
