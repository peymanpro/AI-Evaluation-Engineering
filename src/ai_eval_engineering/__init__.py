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
from .failure_delta import (
    FailureDeltaReport,
    PersistentFailure,
    compare_failure_runs,
)
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
from .promptfoo import (
    SUPPORTED_PROMPTFOO_RESULT_VERSION,
    import_promptfoo_payload,
    load_promptfoo_json,
)
from .release_gate import (
    MetricGateDecision,
    ReleaseGateDecision,
    ReleaseMetricPolicy,
    evaluate_release_candidate,
)
from .result_import import (
    EXTERNAL_RUN_SCHEMA_VERSION,
    export_run_payload,
    import_run_payload,
    load_run_json,
    write_run_json,
)
from .runner import EvaluationRunner, SystemAdapter
from .security import AdversarialCase, AdversarialCategory, summarize_adversarial_cases
from .statistics import ConfidenceInterval, paired_bootstrap_difference_ci
from .tradeoffs import TradeoffObservation, quality_cost_frontier, quality_latency_frontier
from .trajectory import Trajectory, TrajectoryEvent

__all__ = [
    "SUPPORTED_PROMPTFOO_RESULT_VERSION",
    "ABResultAdapter",
    "AdversarialCase",
    "AdversarialCategory",
    "AgentEvaluationResult",
    "AgentSuccessCriteria",
    "AggregatedResult",
    "assess_online_evidence",
    "build_failure_regression_suite",
    "build_metric_contract",
    "building_software_adapter",
    "building_software_suite",
    "calibrate_judge",
    "CalibrationReport",
    "CaseResult",
    "compare_failure_runs",
    "ConfidenceInterval",
    "ContractAdapter",
    "evaluate_agent",
    "evaluate_release_candidate",
    "EvaluationCase",
    "EvaluationRubric",
    "EvaluationRun",
    "EvaluationRunner",
    "EvaluationSuite",
    "evidence_rag_adapter",
    "evidence_rag_suite",
    "EvidenceAssessment",
    "EvidenceIssue",
    "export_run_payload",
    "Exposure",
    "EXTERNAL_RUN_SCHEMA_VERSION",
    "extract_failure_records",
    "FailureDeltaReport",
    "FailureRecord",
    "FakeJudge",
    "GraderResult",
    "how_agents_adapter",
    "how_agents_suite",
    "import_promptfoo_payload",
    "import_run_payload",
    "IntegrationSpec",
    "Judge",
    "JudgeResult",
    "LabelCalibration",
    "load_promptfoo_json",
    "load_run_json",
    "merge_failure_memory",
    "MetricGateDecision",
    "OnlineMetricContract",
    "OnlineObservation",
    "Outcome",
    "paired_bootstrap_difference_ci",
    "PersistentFailure",
    "quality_cost_frontier",
    "quality_latency_frontier",
    "read_failure_memory",
    "ReleaseGateDecision",
    "ReleaseMetricPolicy",
    "RubricDimension",
    "run_contract_demo",
    "RunMetadata",
    "summarize_adversarial_cases",
    "SystemAdapter",
    "SystemOutput",
    "TradeoffObservation",
    "Trajectory",
    "TrajectoryEvent",
    "validate_judge_result",
    "write_evidence_package",
    "write_failure_memory",
    "write_run_json",
]
