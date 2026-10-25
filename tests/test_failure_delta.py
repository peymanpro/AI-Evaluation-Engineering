from __future__ import annotations

import pytest

from ai_eval_engineering.domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from ai_eval_engineering.failure_delta import compare_failure_runs


def make_run(
    run_id: str,
    system_version: str,
    states: dict[tuple[str, str], tuple[bool, float]] | None = None,
    *,
    suite_version: str = "suite-v1",
    system_name: str = "example-assistant",
    case_ids: tuple[str, ...] = ("case-a", "case-b"),
    prompt_prefix: str = "question",
) -> EvaluationRun:
    state_map = states or {}
    results = []
    for case_id in case_ids:
        case = EvaluationCase(
            id=case_id,
            input={"prompt": f"{prompt_prefix} {case_id}"},
            expected={"answer": f"expected {case_id}"},
            metadata={"fixture": True},
            tags=("failure-delta-test",),
        )
        output = SystemOutput(case_id=case_id, output={"answer": f"result {case_id}"})
        graders = []
        for grader_name in ("quality", "safety"):
            passed, score = state_map.get((case_id, grader_name), (True, 0.9))
            graders.append(
                GraderResult(
                    grader=grader_name,
                    passed=passed,
                    score=score,
                    details="passed" if passed else f"{grader_name} failure",
                )
            )
        results.append(CaseResult(case, output, tuple(graders)))

    return EvaluationRun(
        manifest=RunMetadata(
            run_id=run_id,
            suite_version=suite_version,
            system_name=system_name,
            system_version=system_version,
            configuration={},
            seed=17,
            timestamp_utc="2026-10-25T12:00:00Z",
        ),
        cases=tuple(results),
    )


def test_comparison_classifies_new_resolved_and_persistent_failures() -> None:
    baseline = make_run(
        "run-v1",
        "v1",
        {
            ("case-a", "quality"): (False, 0.2),
            ("case-b", "quality"): (False, 0.3),
        },
    )
    candidate = make_run(
        "run-v2",
        "v2",
        {
            ("case-a", "quality"): (False, 0.4),
            ("case-a", "safety"): (False, 0.1),
        },
    )

    report = compare_failure_runs(baseline, candidate)

    assert report.suite_version == "suite-v1"
    assert report.baseline_system_version == "v1"
    assert report.candidate_system_version == "v2"
    assert report.new_failure_count == 1
    assert report.resolved_failure_count == 1
    assert report.persistent_failure_count == 1
    assert report.has_new_regressions
    assert not report.all_baseline_failures_resolved
    assert report.new_failures[0].case.id == "case-a"
    assert report.new_failures[0].grader == "safety"
    assert report.resolved_failures[0].case.id == "case-b"
    assert report.resolved_failures[0].grader == "quality"
    assert report.persistent_failures[0].baseline.case.id == "case-a"
    assert report.persistent_failures[0].baseline.grader == "quality"
    assert report.persistent_failures[0].score_delta == pytest.approx(0.2)
    assert report.summary() == "failure delta: 1 new, 1 resolved, 1 persistent"


def test_clean_candidate_reports_all_baseline_failures_as_resolved() -> None:
    baseline = make_run(
        "run-v1",
        "v1",
        {("case-a", "quality"): (False, 0.2)},
    )
    candidate = make_run("run-v2", "v2")

    report = compare_failure_runs(baseline, candidate)

    assert report.new_failure_count == 0
    assert report.resolved_failure_count == 1
    assert report.persistent_failure_count == 0
    assert not report.has_new_regressions
    assert report.all_baseline_failures_resolved


def test_first_run_failures_are_all_new() -> None:
    baseline = make_run("run-v1", "v1")
    candidate = make_run(
        "run-v2",
        "v2",
        {("case-a", "safety"): (False, 0.0)},
    )

    report = compare_failure_runs(baseline, candidate)

    assert report.new_failure_count == 1
    assert report.resolved_failure_count == 0
    assert report.persistent_failure_count == 0


def test_different_suite_versions_are_rejected() -> None:
    baseline = make_run("run-v1", "v1", suite_version="suite-v1")
    candidate = make_run("run-v2", "v2", suite_version="suite-v2")

    with pytest.raises(ValueError, match="different suite versions"):
        compare_failure_runs(baseline, candidate)


def test_different_system_names_are_rejected() -> None:
    baseline = make_run("run-v1", "v1", system_name="assistant-a")
    candidate = make_run("run-v2", "v2", system_name="assistant-b")

    with pytest.raises(ValueError, match="different system names"):
        compare_failure_runs(baseline, candidate)


def test_changed_case_definition_is_rejected() -> None:
    baseline = make_run("run-v1", "v1", prompt_prefix="old prompt")
    candidate = make_run("run-v2", "v2", prompt_prefix="new prompt")

    with pytest.raises(ValueError, match="case definition changed"):
        compare_failure_runs(baseline, candidate)


def test_missing_or_new_case_ids_are_rejected() -> None:
    baseline = make_run("run-v1", "v1", case_ids=("case-a", "case-b"))
    candidate = make_run("run-v2", "v2", case_ids=("case-a", "case-c"))

    with pytest.raises(ValueError, match="different case IDs"):
        compare_failure_runs(baseline, candidate)


def test_changed_grader_set_is_rejected_not_counted_as_resolved() -> None:
    baseline = make_run(
        "run-v1",
        "v1",
        {("case-a", "safety"): (False, 0.0)},
    )
    candidate = make_run("run-v2", "v2")
    first_case = candidate.cases[0]
    candidate = EvaluationRun(
        candidate.manifest,
        (
            CaseResult(first_case.case, first_case.output, first_case.graders[:1]),
            candidate.cases[1],
        ),
    )

    with pytest.raises(ValueError, match="grader set changed"):
        compare_failure_runs(baseline, candidate)


def test_case_order_does_not_change_failure_classification() -> None:
    baseline = make_run(
        "run-v1",
        "v1",
        {("case-a", "quality"): (False, 0.2)},
    )
    candidate = make_run(
        "run-v2",
        "v2",
        {("case-a", "quality"): (False, 0.4), ("case-b", "safety"): (False, 0.0)},
    )
    candidate = EvaluationRun(candidate.manifest, tuple(reversed(candidate.cases)))

    report = compare_failure_runs(baseline, candidate)

    assert report.new_failure_count == 1
    assert report.persistent_failure_count == 1
    assert report.new_failures[0].case.id == "case-b"
    assert report.persistent_failures[0].score_delta == pytest.approx(0.2)
