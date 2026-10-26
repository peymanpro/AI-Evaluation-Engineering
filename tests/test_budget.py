from __future__ import annotations

import math

import pytest

from ai_eval_engineering.budget import RunBudgetPolicy, assess_run_budget
from ai_eval_engineering.domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    GraderResult,
    RunMetadata,
    SystemOutput,
)


def build_run(rows: list[tuple[str, float | None, float | None, dict[str, object] | None]]) -> EvaluationRun:
    results: list[CaseResult] = []
    for case_id, cost, latency, usage in rows:
        case = EvaluationCase(case_id, {"question": f"question {case_id}"}, expected="ok")
        metadata = {"usage": usage} if usage is not None else {}
        graders = (GraderResult("judge", True, 1.0, "ok", metadata=metadata),)
        output = SystemOutput(case_id, "ok", latency_ms=latency, cost_usd=cost)
        results.append(CaseResult(case, output, graders))
    return EvaluationRun(
        RunMetadata(
            run_id="run-1",
            suite_version="suite-v1",
            system_name="budget-test",
            system_version="revision-1",
            configuration={},
            seed=0,
            timestamp_utc="2026-10-26T00:00:00+00:00",
        ),
        tuple(results),
    )


def test_policy_requires_at_least_one_non_negative_limit() -> None:
    with pytest.raises(ValueError, match="At least one"):
        RunBudgetPolicy()
    with pytest.raises(ValueError, match="non-negative"):
        RunBudgetPolicy(max_total_cost_usd=-0.01)
    with pytest.raises(ValueError, match="finite"):
        RunBudgetPolicy(max_case_latency_ms=math.inf)
    with pytest.raises(TypeError, match="integer"):
        RunBudgetPolicy(max_total_tokens=True)  # type: ignore[arg-type]


def test_complete_run_within_cost_token_and_latency_budgets_passes() -> None:
    run = build_run(
        [
            ("case-a", 0.20, 100.0, {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}),
            ("case-b", 0.30, 200.0, {"prompt_tokens": 15, "completion_tokens": 5, "total_tokens": 20}),
        ]
    )

    result = assess_run_budget(
        run,
        RunBudgetPolicy(
            max_total_cost_usd=0.75,
            max_case_cost_usd=0.40,
            max_total_tokens=40,
            max_case_latency_ms=250,
        ),
    )

    assert result.status == "WITHIN_BUDGET"
    assert result.passed is True
    assert result.total_cost_usd == pytest.approx(0.50)
    assert result.known_cost_subtotal_usd == pytest.approx(0.50)
    assert result.total_tokens == 30
    assert result.highest_observed_case_cost_usd == pytest.approx(0.30)
    assert result.highest_observed_case_latency_ms == pytest.approx(200.0)
    assert result.violations == ()


def test_budget_exceeded_reports_each_measured_violation() -> None:
    run = build_run(
        [
            ("case-expensive", 1.20, 400.0, {"total_tokens": 200}),
            ("case-cheap", 0.30, 150.0, {"total_tokens": 30}),
        ]
    )

    result = assess_run_budget(
        run,
        RunBudgetPolicy(
            max_total_cost_usd=1.0,
            max_case_cost_usd=0.80,
            max_total_tokens=100,
            max_case_latency_ms=300.0,
        ),
    )

    assert result.status == "BUDGET_EXCEEDED"
    assert result.passed is False
    assert {item.metric for item in result.violations} == {
        "total_cost_usd",
        "case_cost_usd",
        "total_tokens",
        "case_latency_ms",
    }
    assert any(item.case_id == "case-expensive" for item in result.violations)


def test_missing_measurements_are_incomplete_not_zero_cost_or_zero_tokens() -> None:
    run = build_run(
        [
            ("case-a", 0.10, 30.0, {"total_tokens": 15}),
            ("case-b", None, None, None),
        ]
    )

    result = assess_run_budget(
        run,
        RunBudgetPolicy(
            max_total_cost_usd=1.0,
            max_total_tokens=100,
            max_case_latency_ms=100.0,
        ),
    )

    assert result.status == "INCOMPLETE_EVIDENCE"
    assert result.passed is False
    assert result.total_cost_usd is None
    assert result.known_cost_subtotal_usd == pytest.approx(0.10)
    assert result.total_tokens is None
    assert result.known_token_subtotal == 15
    assert result.missing_cost_case_ids == ("case-b",)
    assert result.missing_latency_case_ids == ("case-b",)
    assert result.missing_token_case_ids == ("case-b",)
    assert result.violations == ()


def test_known_cost_subtotal_can_prove_budget_exceeded_despite_missing_case_cost() -> None:
    run = build_run(
        [
            ("case-a", 0.80, 100.0, None),
            ("case-b", None, 100.0, None),
        ]
    )

    result = assess_run_budget(run, RunBudgetPolicy(max_total_cost_usd=0.50))

    assert result.status == "BUDGET_EXCEEDED"
    assert result.total_cost_usd is None
    assert result.known_cost_subtotal_usd == pytest.approx(0.80)
    assert result.violations[0].metric == "total_cost_usd"


def test_malformed_non_finite_measurements_produce_invalid_evidence() -> None:
    run = build_run(
        [
            ("case-a", math.nan, 100.0, {"total_tokens": True}),
        ]
    )

    result = assess_run_budget(
        run,
        RunBudgetPolicy(max_total_cost_usd=1.0, max_total_tokens=100),
    )

    assert result.status == "INVALID_EVIDENCE"
    assert result.passed is False
    assert result.total_cost_usd is None
    assert any("cost_usd must be finite" in issue for issue in result.issues)
    assert any("total_tokens" in issue for issue in result.issues)


def test_empty_run_cannot_be_declared_within_budget() -> None:
    run = build_run([])
    result = assess_run_budget(run, RunBudgetPolicy(max_total_cost_usd=1.0))

    assert result.status == "INCOMPLETE_EVIDENCE"
    assert result.passed is False
    assert result.total_cost_usd is None
