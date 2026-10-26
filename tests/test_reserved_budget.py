from __future__ import annotations

import asyncio

import pytest

from ai_eval_engineering.async_runner import AsyncEvaluationRunner
from ai_eval_engineering.budget import (
    RequestBudgetExceeded,
    ReservedBudgetPolicy,
)
from ai_eval_engineering.domain import (
    EvaluationCase,
    EvaluationSuite,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


class CappedSyncAdapter:
    def __init__(self, costs: dict[str, float | None]) -> None:
        self.costs = costs
        self.attempts: list[tuple[str, float]] = []
        self.sent: list[str] = []

    def run(self, case: EvaluationCase) -> SystemOutput:
        raise AssertionError("reserved mode must not use the unbounded adapter entry point")

    def run_with_budget(
        self, case: EvaluationCase, *, max_cost_usd: float
    ) -> SystemOutput:
        self.attempts.append((case.id, max_cost_usd))
        cost = self.costs[case.id]
        if cost is not None and cost > max_cost_usd:
            raise RequestBudgetExceeded("known request quote exceeds supplied allowance")
        self.sent.append(case.id)
        return SystemOutput(
            case_id=case.id,
            output=case.input["answer"],
            latency_ms=10.0,
            cost_usd=cost,
        )


class CappedAsyncAdapter:
    def __init__(self, costs: dict[str, float | None]) -> None:
        self.costs = costs
        self.attempts: list[tuple[str, float]] = []
        self.sent: list[str] = []
        self.active = 0
        self.max_active = 0

    async def run(self, case: EvaluationCase) -> SystemOutput:
        raise AssertionError("reserved mode must not use the unbounded adapter entry point")

    async def run_with_budget(
        self, case: EvaluationCase, *, max_cost_usd: float
    ) -> SystemOutput:
        self.attempts.append((case.id, max_cost_usd))
        cost = self.costs[case.id]
        if cost is not None and cost > max_cost_usd:
            raise RequestBudgetExceeded("known request quote exceeds supplied allowance")
        self.sent.append(case.id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(float(case.input.get("delay", 0.002)))
            return SystemOutput(
                case_id=case.id,
                output=case.input["answer"],
                latency_ms=10.0,
                cost_usd=cost,
            )
        finally:
            self.active -= 1


class CappedPaidGrader:
    def __init__(self, costs: dict[str, float]) -> None:
        self.costs = costs
        self.attempts: list[tuple[str, float]] = []
        self.sent: list[str] = []

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        raise AssertionError("reserved mode must call grade_with_budget for paid graders")

    def grade_with_budget(
        self,
        case: EvaluationCase,
        output: SystemOutput,
        *,
        max_cost_usd: float,
    ) -> GraderResult:
        self.attempts.append((case.id, max_cost_usd))
        cost = self.costs[case.id]
        if cost > max_cost_usd:
            raise RequestBudgetExceeded("grader quote exceeds remaining case allowance")
        self.sent.append(case.id)
        return GraderResult(
            grader="paid-judge",
            passed=True,
            score=1.0,
            details="budget-aware synthetic judge",
            metadata={"cost_usd": cost},
        )


class UnboundedGrader:
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        return GraderResult("unbounded", True, 1.0, "not safe for strict budget")


def make_suite(count: int = 3, *, delays: dict[str, float] | None = None) -> EvaluationSuite:
    delays = delays or {}
    return EvaluationSuite(
        "reserved-budget-v1",
        tuple(
            EvaluationCase(
                id=f"case-{index}",
                input={
                    "answer": f"case-{index}",
                    "delay": delays.get(f"case-{index}", 0.002),
                },
                expected=f"case-{index}",
            )
            for index in range(count)
        ),
    )


def manifest_for(suite: EvaluationSuite) -> RunMetadata:
    return build_run_metadata(suite, "reserved-budget-system", "test-v1", seed=5)


def test_sync_reservation_prevents_request_when_remaining_budget_is_too_small() -> None:
    suite = make_suite()
    adapter = CappedSyncAdapter(
        {"case-0": 0.20, "case-1": 0.20, "case-2": 0.20}
    )
    result = EvaluationRunner(adapter, [ExactMatchGrader()]).run_reserved_budgeted(
        suite,
        manifest_for(suite),
        policy=ReservedBudgetPolicy(max_total_cost_usd=0.50, max_case_cost_usd=0.30),
    )

    assert adapter.sent == ["case-0", "case-1"]
    assert adapter.attempts == [
        ("case-0", pytest.approx(0.30)),
        ("case-1", pytest.approx(0.30)),
        ("case-2", pytest.approx(0.10)),
    ]
    assert tuple(case.case.id for case in result.completed_cases) == ("case-0", "case-1")
    assert result.pending_case_ids == ("case-2",)
    assert result.known_cost_usd == pytest.approx(0.40)
    assert result.reserved_cost_usd == pytest.approx(0.0)
    assert result.status == "BUDGET_LIMIT_REACHED"
    assert result.within_budget is False


def test_sync_reservation_includes_paid_grader_cost_in_case_budget() -> None:
    suite = make_suite()
    adapter = CappedSyncAdapter(
        {"case-0": 0.20, "case-1": 0.20, "case-2": 0.20}
    )
    grader = CappedPaidGrader({"case-0": 0.10, "case-1": 0.10, "case-2": 0.10})

    result = EvaluationRunner(adapter, [grader]).run_reserved_budgeted(
        suite,
        manifest_for(suite),
        policy=ReservedBudgetPolicy(max_total_cost_usd=0.50, max_case_cost_usd=0.30),
    )

    assert adapter.sent == ["case-0", "case-1"]
    assert grader.sent == ["case-0"]
    assert grader.attempts == [("case-0", pytest.approx(0.10))]
    assert tuple(case.case.id for case in result.completed_cases) == ("case-0",)
    assert result.pending_case_ids == ("case-1", "case-2")
    assert result.known_cost_usd == pytest.approx(0.50)
    assert result.status == "BUDGET_LIMIT_REACHED"


def test_sync_missing_cost_keeps_unsettled_reservation_and_stops() -> None:
    suite = make_suite()
    adapter = CappedSyncAdapter({"case-0": None, "case-1": 0.10, "case-2": 0.10})

    result = EvaluationRunner(adapter, [ExactMatchGrader()]).run_reserved_budgeted(
        suite,
        manifest_for(suite),
        policy=ReservedBudgetPolicy(max_total_cost_usd=0.70, max_case_cost_usd=0.30),
    )

    assert adapter.sent == ["case-0"]
    assert result.status == "INCOMPLETE_BUDGET_EVIDENCE"
    assert result.pending_case_ids == ("case-0", "case-1", "case-2")
    assert result.known_cost_usd == 0.0
    assert result.reserved_cost_usd == pytest.approx(0.30)


def test_reserved_mode_rejects_unbounded_components_before_any_request() -> None:
    suite = make_suite()
    adapter = CappedSyncAdapter({case.id: 0.1 for case in suite.cases})
    runner = EvaluationRunner(adapter, [UnboundedGrader()])

    with pytest.raises(TypeError, match="grade_with_budget"):
        runner.run_reserved_budgeted(
            suite,
            manifest_for(suite),
            policy=ReservedBudgetPolicy(max_total_cost_usd=1.0, max_case_cost_usd=0.5),
        )

    assert adapter.sent == []
    assert adapter.attempts == []


def test_async_reservations_cover_all_in_flight_cases_before_launch() -> None:
    suite = make_suite()
    adapter = CappedAsyncAdapter(
        {"case-0": 0.20, "case-1": 0.20, "case-2": 0.20}
    )
    runner = AsyncEvaluationRunner(adapter, [ExactMatchGrader()], max_concurrency=2)

    result = asyncio.run(
        runner.run_reserved_budgeted(
            suite,
            manifest_for(suite),
            policy=ReservedBudgetPolicy(max_total_cost_usd=0.50, max_case_cost_usd=0.30),
        )
    )

    assert adapter.max_active <= 2
    assert set(adapter.sent) == {"case-0", "case-1"}
    assert ("case-1", pytest.approx(0.20)) in adapter.attempts
    assert ("case-2", pytest.approx(0.10)) in adapter.attempts
    assert tuple(case.case.id for case in result.completed_cases) == ("case-0", "case-1")
    assert result.pending_case_ids == ("case-2",)
    assert result.known_cost_usd == pytest.approx(0.40)
    assert result.reserved_cost_usd == pytest.approx(0.0)
    assert result.status == "BUDGET_LIMIT_REACHED"


def test_component_that_exceeds_its_declared_reservation_is_flagged() -> None:
    suite = make_suite(count=1)

    class LyingAdapter(CappedSyncAdapter):
        def run_with_budget(
            self, case: EvaluationCase, *, max_cost_usd: float
        ) -> SystemOutput:
            self.attempts.append((case.id, max_cost_usd))
            self.sent.append(case.id)
            return SystemOutput(case.id, case.input["answer"], cost_usd=max_cost_usd + 0.01)

    adapter = LyingAdapter({"case-0": 0.1})
    result = EvaluationRunner(adapter, [ExactMatchGrader()]).run_reserved_budgeted(
        suite,
        manifest_for(suite),
        policy=ReservedBudgetPolicy(max_total_cost_usd=1.0, max_case_cost_usd=0.30),
    )

    assert result.status == "REQUEST_CAP_VIOLATED"
    assert result.known_cost_usd == pytest.approx(0.31)
    assert result.pending_case_ids == ("case-0",)
    assert result.within_budget is False
