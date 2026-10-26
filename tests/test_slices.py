from __future__ import annotations

import pytest

from ai_eval_engineering import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from ai_eval_engineering.slices import analyze_run_slices


def make_run() -> EvaluationRun:
    rows = (
        (
            EvaluationCase(
                "case-1",
                {"question": "general"},
                expected="answer",
                metadata={"region": "us", "tier": 1},
                tags=("general",),
            ),
            (GraderResult("quality", True, 1.0, "good"), GraderResult("safety", True, 1.0, "safe")),
        ),
        (
            EvaluationCase(
                "case-2",
                {"question": "injection"},
                expected="refuse",
                metadata={"region": "us", "tier": 1},
                tags=("general", "security", "security"),
                risk_category="prompt_injection",
            ),
            (GraderResult("quality", True, 0.9, "good"), GraderResult("safety", False, 0.2, "unsafe")),
        ),
        (
            EvaluationCase(
                "case-3",
                {"question": "unsafe action"},
                expected="refuse",
                metadata={"region": "eu", "tier": True},
                tags=("security",),
                risk_category="prompt_injection",
            ),
            (GraderResult("quality", False, 0.1, "bad"), GraderResult("safety", False, 0.0, "unsafe")),
        ),
        (
            EvaluationCase(
                "case-4",
                {"question": "unclassified"},
                expected="answer",
                metadata={},
                tags=(),
            ),
            (GraderResult("quality", True, 0.95, "good"), GraderResult("safety", True, 1.0, "safe")),
        ),
    )
    return EvaluationRun(
        manifest=RunMetadata(
            run_id="run-1",
            suite_version="suite-v1",
            system_name="assistant",
            system_version="candidate",
            configuration={},
            seed=0,
            timestamp_utc="2026-10-26T00:00:00+00:00",
        ),
        cases=tuple(
            CaseResult(case, SystemOutput(case.id, "observed"), graders)
            for case, graders in rows
        ),
    )


def test_risk_slice_exposes_failures_hidden_by_aggregate() -> None:
    summaries = analyze_run_slices(make_run(), by="risk_category", min_cases=2)
    indexed = {item.value: item for item in summaries}

    injection = indexed["prompt_injection"]
    assert injection.case_count == 2
    assert injection.passed_cases == 0
    assert injection.pass_rate == 0.0
    assert injection.meets_min_cases is True
    assert {metric.grader: metric.pass_rate for metric in injection.grader_metrics} == {
        "quality": 0.5,
        "safety": 0.0,
    }

    missing = indexed[None]
    assert missing.case_count == 2
    assert missing.passed_cases == 2
    assert missing.pass_rate == 1.0


def test_tag_slice_deduplicates_repeated_tags_and_preserves_multi_tag_membership() -> None:
    summaries = {item.value: item for item in analyze_run_slices(make_run(), by="tag")}

    assert summaries["general"].case_count == 2
    assert summaries["security"].case_count == 2
    assert summaries[None].case_count == 1
    assert summaries["security"].passed_cases == 0


def test_metadata_slice_is_explicit_about_missing_values_and_value_types() -> None:
    summaries = analyze_run_slices(make_run(), by="metadata.tier")
    indexed = {(type(item.value).__name__, item.value): item for item in summaries}

    assert indexed[("int", 1)].case_count == 2
    assert indexed[("bool", True)].case_count == 1
    assert indexed[("NoneType", None)].case_count == 1


def test_missing_slices_can_be_excluded_without_dropping_real_groups() -> None:
    summaries = analyze_run_slices(
        make_run(),
        by="risk_category",
        include_missing=False,
    )

    assert [item.value for item in summaries] == ["prompt_injection"]
    assert summaries[0].case_count == 2


@pytest.mark.parametrize("by", ["", "metadata.", "input.question", "tags"])
def test_invalid_slice_dimension_is_rejected(by: str) -> None:
    with pytest.raises(ValueError, match="by must be"):
        analyze_run_slices(make_run(), by=by)


@pytest.mark.parametrize("min_cases", [0, -1])
def test_min_cases_must_be_positive(min_cases: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        analyze_run_slices(make_run(), by="tag", min_cases=min_cases)


def test_non_scalar_metadata_dimension_is_rejected() -> None:
    run = make_run()
    first = run.cases[0]
    case = EvaluationCase(
        first.case.id,
        first.case.input,
        expected=first.case.expected,
        metadata={"region": {"nested": "value"}},
    )
    altered = EvaluationRun(run.manifest, (CaseResult(case, first.output, first.graders),))

    with pytest.raises(TypeError, match="JSON scalar"):
        analyze_run_slices(altered, by="metadata.region")


def test_cases_without_graders_are_rejected() -> None:
    run = make_run()
    first = run.cases[0]
    invalid = EvaluationRun(
        run.manifest,
        (CaseResult(first.case, first.output, ()),),
    )

    with pytest.raises(ValueError, match="no grader results"):
        analyze_run_slices(invalid, by="tag")
