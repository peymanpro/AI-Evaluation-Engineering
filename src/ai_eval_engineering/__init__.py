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
from .runner import EvaluationRunner, SystemAdapter
from .trajectory import Trajectory, TrajectoryEvent

__all__ = [
    "AgentEvaluationResult",
    "AgentSuccessCriteria",
    "AggregatedResult",
    "CaseResult",
    "EvaluationCase",
    "EvaluationRun",
    "EvaluationRunner",
    "EvaluationSuite",
    "GraderResult",
    "RunMetadata",
    "SystemAdapter",
    "SystemOutput",
    "Trajectory",
    "TrajectoryEvent",
    "evaluate_agent",
]
