import pytest
from typing import Any

from ai_eval_engineering import (
    CompositeGrader,
    ContainsGrader,
    JsonFieldGrader,
    NumericToleranceGrader,
    RegexGrader,
)
from ai_eval_engineering.domain import EvaluationCase, GraderResult, SystemOutput
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



def test_empty_expected_substring_fails_instead_of_matching_every_output() -> None:
    result = ContainsGrader().grade(
        EvaluationCase("empty-substring", {}, expected=""),
        SystemOutput("empty-substring", "any response"),
    )

    assert not result.passed
    assert "must not be empty" in result.details


def test_empty_case_regex_fails_instead_of_matching_every_output() -> None:
    result = RegexGrader().grade(
        EvaluationCase("empty-regex", {}, expected=""),
        SystemOutput("empty-regex", "any response"),
    )

    assert not result.passed
    assert "must not be empty" in result.details


def test_numeric_tolerance_rejects_overflow_without_emitting_non_finite_metadata() -> None:
    result = NumericToleranceGrader(rel_tol=1e308).grade(
        EvaluationCase("numeric-overflow", {}, expected=1e308),
        SystemOutput("numeric-overflow", 1e308),
    )

    assert not result.passed
    assert "finite numeric range" in result.details
    assert result.metadata == {}



def test_json_field_grader_checks_nested_object_and_array_paths() -> None:
    case = EvaluationCase(
        "field-match",
        {},
        expected={"allowed": True, "risk": 2},
    )
    output = SystemOutput(
        "field-match",
        {"results": [{"decision": {"allowed": True, "risk": 2.0}}]},
    )

    result = JsonFieldGrader("/results/0/decision").grade(case, output)

    assert result.passed
    assert result.score == 1.0
    assert result.metadata == {"path": "/results/0/decision", "field_found": True}


def test_json_field_grader_supports_json_pointer_escaping() -> None:
    result = JsonFieldGrader("/a~1b/tilde~0").grade(
        EvaluationCase("escaped-path", {}, expected="found"),
        SystemOutput("escaped-path", {"a/b": {"tilde~": "found"}}),
    )

    assert result.passed


def test_json_field_grader_reports_missing_paths_without_leaking_values() -> None:
    result = JsonFieldGrader("/user/secret").grade(
        EvaluationCase("missing-field", {}, expected="private-value"),
        SystemOutput("missing-field", {"user": {}}),
    )

    assert not result.passed
    assert result.metadata == {"path": "/user/secret", "field_found": False}
    assert "private-value" not in result.details


def test_json_field_grader_does_not_treat_boolean_as_number() -> None:
    result = JsonFieldGrader("/active").grade(
        EvaluationCase("bool-number", {}, expected=1),
        SystemOutput("bool-number", {"active": True}),
    )

    assert not result.passed


@pytest.mark.parametrize("path", ["decision", "", "/bad~2escape"])
def test_json_field_grader_rejects_invalid_json_pointer(path: str) -> None:
    with pytest.raises(ValueError, match="JSON Pointer"):
        JsonFieldGrader(path)


def test_composite_grader_weighted_score_and_all_any_pass_modes() -> None:
    case = EvaluationCase("composite", {}, expected="hello")
    output = SystemOutput("composite", "hello world")
    exact = ExactMatchGrader()
    contains = ContainsGrader(name="contains", substring="hello")

    conservative = CompositeGrader([exact, contains], weights=[1, 3])
    permissive = CompositeGrader(
        [exact, contains],
        weights=[1, 3],
        pass_mode="any",
    )
    threshold = CompositeGrader(
        [exact, contains],
        weights=[1, 3],
        pass_mode="score_threshold",
        min_score=0.75,
    )

    conservative_result = conservative.grade(case, output)
    permissive_result = permissive.grade(case, output)
    threshold_result = threshold.grade(case, output)

    assert conservative_result.score == pytest.approx(0.75)
    assert not conservative_result.passed
    assert permissive_result.score == pytest.approx(0.75)
    assert permissive_result.passed
    assert threshold_result.passed
    assert threshold_result.metadata["pass_mode"] == "score_threshold"
    assert len(threshold_result.metadata["components"]) == 2


def test_composite_grader_rejects_duplicate_component_names() -> None:
    grader = CompositeGrader(
        [
            ExactMatchGrader(name="same"),
            ContainsGrader(name="same", substring="hello"),
        ]
    )

    with pytest.raises(ValueError, match="Duplicate grader name"):
        grader.grade(
            EvaluationCase("duplicate-component", {}, expected="hello"),
            SystemOutput("duplicate-component", "hello"),
        )


class OutOfRangeScoreGrader:
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        return GraderResult("out_of_range", True, 1.5, "invalid component score")


def test_composite_grader_rejects_component_scores_outside_zero_to_one() -> None:
    grader = CompositeGrader([OutOfRangeScoreGrader()])

    with pytest.raises(ValueError, match="score in \[0, 1\]"):
        grader.grade(
            EvaluationCase("out-of-range", {}, expected="answer"),
            SystemOutput("out-of-range", "answer"),
        )


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"weights": [1.0]}, ValueError, "one value per component"),
        ({"weights": [1.0, 0.0]}, ValueError, "greater than zero"),
        ({"weights": [float("inf"), 1.0]}, ValueError, "finite"),
        ({"pass_mode": "majority"}, ValueError, "pass_mode"),
        ({"min_score": 1.1}, ValueError, "between 0 and 1"),
    ],
)
def test_composite_grader_rejects_invalid_configuration(
    kwargs: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        CompositeGrader([ExactMatchGrader(), ContainsGrader()], **kwargs)
