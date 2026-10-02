"""Provider-neutral repository integration adapters."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .domain import EvaluationCase, EvaluationSuite, JsonObject, SystemOutput
from .graders import ExactMatchGrader, TrajectoryGrader
from .runner import EvaluationRunner, build_run_metadata


@dataclass(frozen=True)
class IntegrationSpec:
    repository: str
    revision: str
    description: str


class ContractAdapter:
    """Adapt a deterministic repository contract into the generic SUT interface."""

    def __init__(
        self,
        spec: IntegrationSpec,
        handler: Callable[[EvaluationCase], SystemOutput],
    ) -> None:
        self.spec = spec
        self._handler = handler

    def run(self, case: EvaluationCase) -> SystemOutput:
        return self._handler(case)


def run_contract_demo(
    suite: EvaluationSuite,
    adapter: ContractAdapter,
    graders: list[Any],
) -> tuple[dict[str, Any], IntegrationSpec]:
    runner = EvaluationRunner(adapter, graders)
    manifest = build_run_metadata(
        suite,
        adapter.spec.repository,
        adapter.spec.revision,
        {"integration": adapter.spec.description},
        seed=0,
    )
    run = runner.run(suite, manifest)
    return {
        "run": run,
        "passed_cases": sum(
            all(grader.passed for grader in result.graders)
            for result in run.cases
        ),
    }, adapter.spec


def building_software_spec() -> IntegrationSpec:
    return IntegrationSpec(
        "peymanpro/Building-Software-With-LLMs",
        "main",
        "Deterministic FakeLlmProvider evaluation contract.",
    )


def evidence_rag_spec() -> IntegrationSpec:
    return IntegrationSpec(
        "peymanpro/Evidence-Grounded-RAG",
        "main",
        "Retrieval/evidence evaluation contract.",
    )


def how_agents_spec() -> IntegrationSpec:
    return IntegrationSpec(
        "peymanpro/HowAgentsWork",
        "main",
        "Deterministic agent scenario and trajectory contract.",
    )


def building_software_adapter() -> ContractAdapter:
    expected = {
        "greeting": "general_inquiry",
        "shipped": "Shipped",
        "delayed": "Delayed",
        "delivered": "Delivered",
    }

    def handler(case: EvaluationCase) -> SystemOutput:
        return SystemOutput(case_id=case.id, output=expected[case.id])

    return ContractAdapter(building_software_spec(), handler)


def evidence_rag_adapter() -> ContractAdapter:
    expected = {"supported": "grounded", "unsupported": "insufficient_evidence"}

    def handler(case: EvaluationCase) -> SystemOutput:
        return SystemOutput(case.id, expected[case.id])

    return ContractAdapter(evidence_rag_spec(), handler)


def how_agents_adapter() -> ContractAdapter:
    expected_tools: dict[str, list[str]] = {
        "late": [
            "get_order",
            "get_tracking",
            "get_policy",
            "get_customer_history",
            "create_escalation",
        ],
        "recent": ["get_order", "get_tracking", "get_policy", "get_customer_history"],
        "within_policy": ["get_order", "get_tracking", "get_policy"],
    }

    def handler(case: EvaluationCase) -> SystemOutput:
        tools = expected_tools[case.id]
        trace: list[JsonObject] = [
            {
                "step": step,
                "kind": "action",
                "name": tool,
                "tool_name": tool,
            }
            for step, tool in enumerate(tools, start=1)
        ]
        trace.append({"step": len(tools) + 1, "kind": "termination", "name": "finish"})
        return SystemOutput(case.id, "success", trace=trace)

    return ContractAdapter(how_agents_spec(), handler)


def building_software_suite() -> EvaluationSuite:
    cases = [
        ("greeting", "general_inquiry"),
        ("shipped", "Shipped"),
        ("delayed", "Delayed"),
        ("delivered", "Delivered"),
    ]
    return EvaluationSuite(
        "building-software-1",
        tuple(EvaluationCase(case_id, {}, expected=value) for case_id, value in cases),
    )


def evidence_rag_suite() -> EvaluationSuite:
    return EvaluationSuite(
        "evidence-rag-1",
        (
            EvaluationCase("supported", {}, expected="grounded"),
            EvaluationCase("unsupported", {}, expected="insufficient_evidence"),
        ),
    )


def how_agents_suite() -> EvaluationSuite:
    return EvaluationSuite(
        "how-agents-1",
        tuple(
            EvaluationCase(case_id, {"expected_success": True}, expected="success")
            for case_id in ("late", "recent", "within_policy")
        ),
    )


def standard_integration_graders(repository: str) -> list[Any]:
    if repository.endswith("HowAgentsWork"):
        return [
            ExactMatchGrader(),
            TrajectoryGrader(
                required_tools={"get_order"},
                forbidden_tools={"delete"},
                max_steps=6,
            ),
        ]
    return [ExactMatchGrader()]
