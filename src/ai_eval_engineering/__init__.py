"""Provider-neutral building blocks for AI evaluation engineering."""

from .agent import AgentEvaluationResult, AgentSuccessCriteria, evaluate_agent
from .domain import (
    AggregatedResult,
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from .evidence import write_evidence_package
from .online import Exposure, OnlineMetricContract, OnlineObservation, Outcome, build_metric_contract
from .integrations import (
    ContractAdapter,
    IntegrationSpec,
    building_software_adapter,
    building_software_suite,
    evidence_rag_adapter,
    evidence_rag_suite,
    how_agents_adapter,
    how_agents_suite,
    run_contract_demo,
)
from .runner import EvaluationRunner, SystemAdapter
from .security import AdversarialCase, AdversarialCategory, summarize_adversarial_cases
from .tradeoffs import TradeoffObservation, quality_cost_frontier, quality_latency_frontier
from .trajectory import Trajectory, TrajectoryEvent

__all__ = [
    "AdversarialCase",
    "AdversarialCategory",
    "AgentEvaluationResult",
    "AgentSuccessCriteria",
    "AggregatedResult",
    "CaseResult",
    "ContractAdapter",
    "EvaluationCase",
    "EvaluationRun",
    "EvaluationRunner",
    "EvaluationSuite",
    "Exposure",
    "GraderResult",
    "IntegrationSpec",
    "OnlineMetricContract",
    "OnlineObservation",
    "Outcome",
    "RunMetadata",
    "SystemAdapter",
    "SystemOutput",
    "TradeoffObservation",
    "Trajectory",
    "TrajectoryEvent",
    "building_software_adapter",
    "building_software_suite",
    "build_metric_contract",
    "evaluate_agent",
    "evidence_rag_adapter",
    "evidence_rag_suite",
    "how_agents_adapter",
    "how_agents_suite",
    "quality_cost_frontier",
    "quality_latency_frontier",
    "run_contract_demo",
    "summarize_adversarial_cases",
    "write_evidence_package",
]
