"""Offline demonstration of pre-request cost reservations.

This example makes no provider calls. The adapters are deterministic stand-ins that
illustrate the contract a real provider adapter must implement: reject requests whose
worst-case quote cannot fit the allowance before submitting anything billable.
"""

from __future__ import annotations

from ai_eval_engineering import (
    EvaluationCase,
    EvaluationSuite,
    GraderResult,
    ReservedBudgetPolicy,
    RequestBudgetExceeded,
    SystemOutput,
)
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


class QuotedSystemAdapter:
    """A test adapter that checks a known worst-case quote before dispatch."""

    def __init__(self, quoted_costs: dict[str, float]) -> None:
        self.quoted_costs = quoted_costs
        self.sent_case_ids: list[str] = []

    def run(self, case: EvaluationCase) -> SystemOutput:
        raise AssertionError("reserved execution must use run_with_budget")

    def run_with_budget(
        self, case: EvaluationCase, *, max_cost_usd: float
    ) -> SystemOutput:
        quoted_cost = self.quoted_costs[case.id]
        if quoted_cost > max_cost_usd:
            raise RequestBudgetExceeded(
                f"quoted cost {quoted_cost:.4f} exceeds allowance {max_cost_usd:.4f} USD"
            )
        # A real adapter must translate max_cost_usd to enforceable request
        # constraints before calling the provider. This sample simulates that.
        self.sent_case_ids.append(case.id)
        return SystemOutput(
            case_id=case.id,
            output=case.input["answer"],
            latency_ms=10.0,
            cost_usd=quoted_cost,
        )


class QuotedJudge:
    """A test grader whose quote and actual cost are known in advance."""

    budget_cost_free = False

    def __init__(self, quoted_costs: dict[str, float]) -> None:
        self.quoted_costs = quoted_costs
        self.sent_case_ids: list[str] = []

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        raise AssertionError("reserved execution must use grade_with_budget")

    def grade_with_budget(
        self,
        case: EvaluationCase,
        output: SystemOutput,
        *,
        max_cost_usd: float,
    ) -> GraderResult:
        quoted_cost = self.quoted_costs[case.id]
        if quoted_cost > max_cost_usd:
            raise RequestBudgetExceeded(
                f"quoted grader cost {quoted_cost:.4f} exceeds allowance "
                f"{max_cost_usd:.4f} USD"
            )
        # In a real judge, reported cost should be reconciled with provider usage.
        self.sent_case_ids.append(case.id)
        return GraderResult(
            grader="quoted_judge",
            passed=True,
            score=1.0,
            details="synthetic quote-based grade",
            metadata={"cost_usd": quoted_cost},
        )


def main() -> None:
    suite = EvaluationSuite(
        version="reserved-budget-demo-v1",
        cases=tuple(
            EvaluationCase(
                id=f"case-{index}",
                input={"answer": f"answer-{index}"},
                expected=f"answer-{index}",
            )
            for index in range(4)
        ),
    )
    adapter = QuotedSystemAdapter({case.id: 0.04 for case in suite.cases})
    judge = QuotedJudge({case.id: 0.01 for case in suite.cases})
    runner = EvaluationRunner(adapter, [judge])

    result = runner.run_reserved_budgeted(
        suite,
        build_run_metadata(suite, "quoted-system", "demo-v1", seed=7),
        policy=ReservedBudgetPolicy(
            max_total_cost_usd=0.10,
            max_case_cost_usd=0.05,
        ),
    )

    print("status:", result.status)
    print("known cost USD:", result.known_cost_usd)
    print("reserved cost USD:", result.reserved_cost_usd)
    print("completed:", [case.case.id for case in result.completed_cases])
    print("incomplete:", result.incomplete_case_ids)
    print("not started:", result.not_started_case_ids)

    assert result.status == "BUDGET_LIMIT_REACHED"
    assert adapter.sent_case_ids == ["case-0", "case-1"]
    assert judge.sent_case_ids == ["case-0", "case-1"]
    assert result.known_cost_usd == 0.10
    assert result.pending_case_ids == ("case-2", "case-3")
    assert result.incomplete_case_ids == ()
    assert result.not_started_case_ids == ("case-2", "case-3")


if __name__ == "__main__":
    main()
