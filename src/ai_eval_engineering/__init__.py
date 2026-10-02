"""Provider-neutral building blocks for AI evaluation engineering."""

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

__all__ = [
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
]
