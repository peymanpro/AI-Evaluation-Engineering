from __future__ import annotations

import asyncio
from pathlib import Path

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



def test_zero_total_budget_starts_no_reserved_request() -> None:
    suite = make_suite()
    adapter = CappedSyncAdapter({case.id: 0.1 for case in suite.cases})

    result = EvaluationRunner(adapter, [ExactMatchGrader()]).run_reserved_budgeted(
        suite,
        manifest_for(suite),
        policy=ReservedBudgetPolicy(max_total_cost_usd=0.0, max_case_cost_usd=0.30),
    )

    assert adapter.attempts == []
    assert result.completed_cases == ()
    assert result.pending_case_ids == tuple(case.id for case in suite.cases)
    assert result.incomplete_case_ids == ()
    assert result.not_started_case_ids == tuple(case.id for case in suite.cases)
    assert result.status == "BUDGET_LIMIT_REACHED"


def test_empty_suite_does_not_claim_reserved_budget_compliance() -> None:
    suite = EvaluationSuite("empty-v1", ())
    adapter = CappedSyncAdapter({})
    result = EvaluationRunner(adapter, [ExactMatchGrader()]).run_reserved_budgeted(
        suite,
        manifest_for(suite),
        policy=ReservedBudgetPolicy(max_total_cost_usd=1.0, max_case_cost_usd=0.5),
    )

    assert adapter.attempts == []
    assert result.status == "INCOMPLETE_BUDGET_EVIDENCE"
    assert result.within_budget is False
    assert result.pending_case_ids == ()
    assert result.incomplete_case_ids == ()
    assert result.not_started_case_ids == ()


def test_reserved_policy_rejects_non_positive_case_ceiling() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        ReservedBudgetPolicy(max_total_cost_usd=1.0, max_case_cost_usd=0.0)


def test_reserved_mode_rejects_configured_retries_before_requests() -> None:
    from ai_eval_engineering.retry import RetryPolicy

    suite = make_suite()
    adapter = CappedSyncAdapter({case.id: 0.1 for case in suite.cases})
    retry_policy = RetryPolicy(max_attempts=2)
    runner = EvaluationRunner(
        adapter,
        [ExactMatchGrader()],
        retry_policy=retry_policy,
    )

    with pytest.raises(ValueError, match="does not allow retries"):
        runner.run_reserved_budgeted(
            suite,
            build_run_metadata(
                suite,
                "reserved-budget-system",
                "test-v1",
                seed=5,
                retry_policy=retry_policy,
            ),
            policy=ReservedBudgetPolicy(max_total_cost_usd=1.0, max_case_cost_usd=0.5),
        )

    assert adapter.attempts == []

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
    assert result.incomplete_case_ids == ("case-1",)
    assert result.unresolved_cost_case_ids == ()
    assert result.not_started_case_ids == ("case-2",)
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
    assert result.incomplete_case_ids == ("case-0",)
    assert result.unresolved_cost_case_ids == ("case-0",)
    assert result.not_started_case_ids == ("case-1", "case-2")
    assert result.known_cost_usd == 0.0
    assert result.reserved_cost_usd == pytest.approx(0.30)



def test_checkpointed_case_at_exact_case_cap_is_not_false_positive(tmp_path: Path) -> None:
    class CheckpointAdapter:
        def run(self, case: EvaluationCase) -> SystemOutput:
            return SystemOutput(
                case.id,
                case.input["answer"],
                latency_ms=10.0,
                cost_usd=0.20,
            )

        def run_with_budget(
            self, case: EvaluationCase, *, max_cost_usd: float
        ) -> SystemOutput:
            raise AssertionError("checkpoint should be reused without a new request")

    class CheckpointPaidGrader:
        def _result(self) -> GraderResult:
            return GraderResult(
                grader="paid-checkpoint-judge",
                passed=True,
                score=1.0,
                details="recorded paid grader",
                metadata={"cost_usd": 0.10},
            )

        def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
            return self._result()

        def grade_with_budget(
            self,
            case: EvaluationCase,
            output: SystemOutput,
            *,
            max_cost_usd: float,
        ) -> GraderResult:
            raise AssertionError("checkpoint grader should not be rerun")

    suite = make_suite(count=1)
    manifest = manifest_for(suite)
    adapter = CheckpointAdapter()
    grader = CheckpointPaidGrader()
    runner = EvaluationRunner(adapter, [grader])
    checkpoint = tmp_path / "reserved-budget-checkpoint.json"

    runner.run(suite, manifest, checkpoint_path=checkpoint)
    result = runner.run_reserved_budgeted(
        suite,
        manifest,
        policy=ReservedBudgetPolicy(max_total_cost_usd=0.50, max_case_cost_usd=0.30),
        checkpoint_path=checkpoint,
    )

    assert result.status == "COMPLETED"
    assert result.known_cost_usd == pytest.approx(0.30)
    assert result.reserved_cost_usd == pytest.approx(0.0)
    assert result.pending_case_ids == ()
    assert result.incomplete_case_ids == ()
    assert result.unresolved_cost_case_ids == ()
    assert result.within_budget is True

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



def test_async_reservation_includes_paid_grader_cost_in_case_budget() -> None:
    suite = make_suite()
    adapter = CappedAsyncAdapter(
        {"case-0": 0.20, "case-1": 0.20, "case-2": 0.20}
    )
    grader = CappedPaidGrader({"case-0": 0.10, "case-1": 0.10, "case-2": 0.10})

    result = asyncio.run(
        AsyncEvaluationRunner(adapter, [grader], max_concurrency=2).run_reserved_budgeted(
            suite,
            manifest_for(suite),
            policy=ReservedBudgetPolicy(max_total_cost_usd=0.50, max_case_cost_usd=0.30),
        )
    )

    assert set(adapter.sent) == {"case-0", "case-1"}
    assert grader.sent == ["case-0"]
    assert tuple(case.case.id for case in result.completed_cases) == ("case-0",)
    assert result.pending_case_ids == ("case-1", "case-2")
    assert result.incomplete_case_ids == ("case-1",)
    assert result.not_started_case_ids == ("case-2",)
    assert result.known_cost_usd == pytest.approx(0.50)
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
    assert result.incomplete_case_ids == ("case-0",)
    assert result.unresolved_cost_case_ids == ()
    assert result.within_budget is False

def test_async_missing_cost_evidence_is_not_hidden_by_concurrent_budget_stop() -> None:
    suite = make_suite(2)

    class MissingThenDeclinedAdapter:
        def __init__(self) -> None:
            self.sibling_declined = asyncio.Event()

        async def run(self, case: EvaluationCase) -> SystemOutput:
            raise AssertionError("reserved execution must use run_with_budget")

        async def run_with_budget(
            self, case: EvaluationCase, *, max_cost_usd: float
        ) -> SystemOutput:
            if case.id == "case-0":
                # Ensure the sibling first records BUDGET_LIMIT_REACHED, then
                # return missing charge evidence to test status-priority logic.
                await self.sibling_declined.wait()
                return SystemOutput(
                    case_id=case.id,
                    output=case.input["answer"],
                    latency_ms=10.0,
                    cost_usd=None,
                )
            self.sibling_declined.set()
            raise RequestBudgetExceeded("known quote does not fit its reservation")

    async def run_scenario():
        adapter = MissingThenDeclinedAdapter()
        return await AsyncEvaluationRunner(
            adapter, [ExactMatchGrader()], max_concurrency=2
        ).run_reserved_budgeted(
            suite,
            manifest_for(suite),
            policy=ReservedBudgetPolicy(
                max_total_cost_usd=1.0,
                max_case_cost_usd=0.5,
            ),
        )

    result = asyncio.run(run_scenario())

    assert result.status == "INCOMPLETE_BUDGET_EVIDENCE"
    assert result.unresolved_cost_case_ids == ("case-0",)
    assert result.incomplete_case_ids == ("case-0",)
    assert result.not_started_case_ids == ("case-1",)
    assert result.known_cost_usd == 0.0
    assert result.reserved_cost_usd == pytest.approx(0.5)
