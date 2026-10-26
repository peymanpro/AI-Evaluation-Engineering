from __future__ import annotations

import asyncio

import pytest

from ai_eval_engineering.async_runner import AsyncEvaluationRunner
from ai_eval_engineering.budget import RunBudgetPolicy
from ai_eval_engineering.domain import (
    EvaluationCase,
    EvaluationSuite,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


class CostAdapter:
    def __init__(self, costs: dict[str, float | None]) -> None:
        self.costs = costs
        self.calls: list[str] = []

    def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls.append(case.id)
        return SystemOutput(
            case_id=case.id,
            output=case.input["answer"],
            latency_ms=case.input.get("latency_ms", 10.0),
            cost_usd=self.costs[case.id],
        )


class AsyncCostAdapter:
    def __init__(self, costs: dict[str, float | None]) -> None:
        self.costs = costs
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls.append(case.id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(float(case.input.get("delay", 0.001)))
            return SystemOutput(
                case_id=case.id,
                output=case.input["answer"],
                latency_ms=case.input.get("latency_ms", 10.0),
                cost_usd=self.costs[case.id],
            )
        finally:
            self.active -= 1


class UsageGrader:
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        return GraderResult(
            grader="usage",
            passed=True,
            score=1.0,
            details="synthetic usage for budget tests",
            metadata={"usage": {"total_tokens": case.input["tokens"]}},
        )


def make_suite(count: int = 4, *, tokens: int = 3) -> EvaluationSuite:
    return EvaluationSuite(
        "live-budget-suite-v1",
        tuple(
            EvaluationCase(
                id=f"case-{index}",
                input={"answer": f"case-{index}", "tokens": tokens},
                expected=f"case-{index}",
            )
            for index in range(count)
        ),
    )


def manifest_for(suite: EvaluationSuite) -> RunMetadata:
    return build_run_metadata(suite, "budget-test-system", "test-v1", seed=3)


def test_sync_runner_stops_before_starting_cases_after_total_cost_cap() -> None:
    suite = make_suite()
    adapter = CostAdapter(
        {"case-0": 0.30, "case-1": 0.25, "case-2": 0.01, "case-3": 0.01}
    )
    runner = EvaluationRunner(adapter, [ExactMatchGrader()])

    result = runner.run_budgeted(
        suite,
        manifest_for(suite),
        policy=RunBudgetPolicy(max_total_cost_usd=0.50),
    )

    assert adapter.calls == ["case-0", "case-1"]
    assert tuple(item.case.id for item in result.completed_cases) == ("case-0", "case-1")
    assert result.pending_case_ids == ("case-2", "case-3")
    assert result.status == "BUDGET_LIMIT_REACHED"
    assert result.known_cost_usd == pytest.approx(0.55)
    assert result.all_cases_completed is False
    assert result.within_budget is False
    assert result.stop_reason is not None


def test_zero_total_budget_stops_before_any_provider_call() -> None:
    suite = make_suite()
    adapter = CostAdapter({case.id: 0.0 for case in suite.cases})
    result = EvaluationRunner(adapter, [ExactMatchGrader()]).run_budgeted(
        suite,
        manifest_for(suite),
        policy=RunBudgetPolicy(max_total_cost_usd=0.0),
    )

    assert adapter.calls == []
    assert result.completed_cases == ()
    assert result.pending_case_ids == tuple(case.id for case in suite.cases)
    assert result.status == "BUDGET_LIMIT_REACHED"


def test_missing_cost_evidence_fails_closed_before_next_case() -> None:
    suite = make_suite()
    adapter = CostAdapter(
        {"case-0": None, "case-1": 0.01, "case-2": 0.01, "case-3": 0.01}
    )
    result = EvaluationRunner(adapter, [ExactMatchGrader()]).run_budgeted(
        suite,
        manifest_for(suite),
        policy=RunBudgetPolicy(max_total_cost_usd=1.0),
    )

    assert adapter.calls == ["case-0"]
    assert result.status == "INCOMPLETE_BUDGET_EVIDENCE"
    assert result.pending_case_ids == ("case-1", "case-2", "case-3")
    assert "no cost measurement" in (result.stop_reason or "")


def test_sync_runner_stops_when_grader_token_usage_reaches_cap() -> None:
    suite = make_suite(tokens=3)
    adapter = CostAdapter({case.id: None for case in suite.cases})
    result = EvaluationRunner(adapter, [UsageGrader()]).run_budgeted(
        suite,
        manifest_for(suite),
        policy=RunBudgetPolicy(max_total_tokens=5),
    )

    assert adapter.calls == ["case-0", "case-1"]
    assert result.known_tokens == 6
    assert result.pending_case_ids == ("case-2", "case-3")
    assert result.status == "BUDGET_LIMIT_REACHED"


def test_sync_runner_stops_after_a_per_case_cost_violation() -> None:
    suite = make_suite()
    adapter = CostAdapter(
        {"case-0": 0.30, "case-1": 0.60, "case-2": 0.01, "case-3": 0.01}
    )
    result = EvaluationRunner(adapter, [ExactMatchGrader()]).run_budgeted(
        suite,
        manifest_for(suite),
        policy=RunBudgetPolicy(max_case_cost_usd=0.50),
    )

    assert adapter.calls == ["case-0", "case-1"]
    assert result.status == "BUDGET_LIMIT_REACHED"
    assert result.pending_case_ids == ("case-2", "case-3")


def test_async_runner_completes_current_batch_but_does_not_start_another() -> None:
    suite = make_suite()
    adapter = AsyncCostAdapter(
        {"case-0": 0.40, "case-1": 0.40, "case-2": 0.01, "case-3": 0.01}
    )
    runner = AsyncEvaluationRunner(
        adapter,
        [ExactMatchGrader()],
        max_concurrency=2,
    )

    result = asyncio.run(
        runner.run_budgeted(
            suite,
            manifest_for(suite),
            policy=RunBudgetPolicy(max_total_cost_usd=0.50),
        )
    )

    assert set(adapter.calls) == {"case-0", "case-1"}
    assert adapter.max_active == 2
    assert tuple(item.case.id for item in result.completed_cases) == ("case-0", "case-1")
    assert result.pending_case_ids == ("case-2", "case-3")
    assert result.known_cost_usd == pytest.approx(0.80)
    assert result.status == "BUDGET_LIMIT_REACHED"


def test_async_runner_fails_closed_when_cost_is_unavailable() -> None:
    suite = make_suite()
    adapter = AsyncCostAdapter(
        {"case-0": None, "case-1": 0.01, "case-2": 0.01, "case-3": 0.01}
    )
    result = asyncio.run(
        AsyncEvaluationRunner(adapter, [ExactMatchGrader()], max_concurrency=1).run_budgeted(
            suite,
            manifest_for(suite),
            policy=RunBudgetPolicy(max_total_cost_usd=1.0),
        )
    )

    assert adapter.calls == ["case-0"]
    assert result.status == "INCOMPLETE_BUDGET_EVIDENCE"
    assert result.pending_case_ids == ("case-1", "case-2", "case-3")
