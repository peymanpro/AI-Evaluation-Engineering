"""Agent task and step-level evaluation criteria."""
from __future__ import annotations

from dataclasses import dataclass

from .trajectory import Trajectory


@dataclass(frozen=True)
class AgentSuccessCriteria:
    expected_task_success: bool = True
    required_tools: frozenset[str] = frozenset()
    forbidden_tools: frozenset[str] = frozenset()
    max_steps: int | None = None
    require_termination: bool = True
    min_required_actions: int = 0


@dataclass(frozen=True)
class AgentEvaluationResult:
    task_success: bool
    step_success: bool
    safe: bool
    efficient: bool
    passed: bool
    violations: tuple[str, ...]

    @property
    def score(self) -> float:
        signals = (self.task_success, self.step_success, self.safe, self.efficient)
        return sum(signals) / len(signals)


def evaluate_agent(
    criteria: AgentSuccessCriteria,
    trajectory: Trajectory,
    task_success: bool,
) -> AgentEvaluationResult:
    trajectory.validate()
    tools = set(trajectory.tool_names)
    violations: list[str] = []

    step_success = True
    if criteria.require_termination and not trajectory.terminated:
        step_success = False
        violations.append("trajectory did not terminate")

    missing = criteria.required_tools - tools
    if missing:
        step_success = False
        violations.append(f"required tools missing: {', '.join(sorted(missing))}")

    if trajectory.step_count < criteria.min_required_actions:
        step_success = False
        violations.append(
            f"trajectory has {trajectory.step_count} steps; "
            f"minimum is {criteria.min_required_actions}"
        )

    forbidden = tools & criteria.forbidden_tools
    safe = not forbidden
    if forbidden:
        violations.append(f"forbidden tools used: {', '.join(sorted(forbidden))}")

    efficient = criteria.max_steps is None or trajectory.step_count <= criteria.max_steps
    if not efficient:
        violations.append(
            f"trajectory has {trajectory.step_count} steps; max is {criteria.max_steps}"
        )

    task_ok = task_success == criteria.expected_task_success
    if not task_ok:
        violations.append(
            f"task success={task_success!r}; expected {criteria.expected_task_success!r}"
        )

    return AgentEvaluationResult(
        task_success=task_ok,
        step_success=step_success,
        safe=safe,
        efficient=efficient,
        passed=task_ok and step_success and safe and efficient,
        violations=tuple(violations),
    )
