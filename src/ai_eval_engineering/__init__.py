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
from .evidence_guardrails import EvidenceAssessment, EvidenceIssue, assess_online_evidence
from .failure_memory import (
    FailureRecord,
    build_failure_regression_suite,
    extract_failure_records,
    merge_failure_memory,
    read_failure_memory,
    write_failure_memory,
)
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
from .judge import (
    CalibrationReport,
    EvaluationRubric,
    FakeJudge,
    Judge,
    JudgeResult,
    LabelCalibration,
    RubricDimension,
    calibrate_judge,
    validate_judge_result,
)
from .online import (
    ABResultAdapter,
    Exposure,
    OnlineMetricContract,
    OnlineObservation,
    Outcome,
    build_metric_contract,
)
from .release_gate import (
    MetricGateDecision,
    ReleaseGateDecision,
    ReleaseMetricPolicy,
    evaluate_release_candidate,
)
from .runner import EvaluationRunner, SystemAdapter
from .security import AdversarialCase, AdversarialCategory, summarize_adversarial_cases
from .statistics import ConfidenceInterval, paired_bootstrap_difference_ci
from .tradeoffs import TradeoffObservation, quality_cost_frontier, quality_latency_frontier
from .trajectory import Trajectory, TrajectoryEvent

__all__ = [
    "ABResultAdapter",
    "AdversarialCase",
    "AdversarialCategory",
    "AgentEvaluationResult",
    "AgentSuccessCriteria",
    "AggregatedResult",
    "CalibrationReport",
    "CaseResult",
    "ConfidenceInterval",
    "ContractAdapter",
    "EvaluationCase",
    "EvaluationRubric",
    "EvaluationRun",
    "EvaluationRunner",
    "EvaluationSuite",
    "EvidenceAssessment",
    "EvidenceIssue",
    "Exposure",
    "FailureRecord",
    "FakeJudge",
    "GraderResult",
    "IntegrationSpec",
    "Judge",
    "JudgeResult",
    "LabelCalibration",
    "MetricGateDecision",
    "OnlineMetricContract",
    "OnlineObservation",
    "Outcome",
    "ReleaseGateDecision",
    "ReleaseMetricPolicy",
    "RubricDimension",
    "RunMetadata",
    "SystemAdapter",
    "SystemOutput",
    "TradeoffObservation",
    "Trajectory",
    "TrajectoryEvent",
    "assess_online_evidence",
    "build_failure_regression_suite",
    "build_metric_contract",
    "building_software_adapter",
    "building_software_suite",
    "calibrate_judge",
    "evaluate_agent",
    "evaluate_release_candidate",
    "evidence_rag_adapter",
    "evidence_rag_suite",
    "extract_failure_records",
    "how_agents_adapter",
    "how_agents_suite",
    "merge_failure_memory",
    "paired_bootstrap_difference_ci",
    "quality_cost_frontier",
    "quality_latency_frontier",
    "read_failure_memory",
    "run_contract_demo",
    "summarize_adversarial_cases",
    "validate_judge_result",
    "write_evidence_package",
    "write_failure_memory",
]
