from ai_eval_engineering.agent import AgentSuccessCriteria, evaluate_agent
from ai_eval_engineering.domain import SystemOutput
from ai_eval_engineering.trajectory import Trajectory, TrajectoryEvent


def test_trajectory_replay_preserves_order_and_termination() -> None:
    trajectory = Trajectory.from_events(
        [
            TrajectoryEvent(1, "action", "search", {"tool_name": "search"}),
            TrajectoryEvent(1, "tool_result", "search", {"ok": True}),
            TrajectoryEvent(2, "termination", "finish", {}),
        ]
    )
    assert trajectory.terminated
    assert trajectory.step_count == 2
    assert trajectory.replay()[0]["kind"] == "action"


def test_trajectory_from_output_supports_legacy_trace() -> None:
    trajectory = Trajectory.from_system_output(
        SystemOutput("a", "done", trace=[{"tool_name": "search"}, {"tool_name": "finish"}])
    )
    assert trajectory.tool_names == ("search",)
    assert trajectory.step_count == 2


def test_agent_evaluation_separates_task_safety_and_efficiency() -> None:
    trajectory = Trajectory.from_events(
        [
            TrajectoryEvent(1, "action", "search", {"tool_name": "search"}),
            TrajectoryEvent(2, "action", "delete", {"tool_name": "delete"}),
            TrajectoryEvent(3, "termination", "finish", {}),
        ]
    )
    result = evaluate_agent(
        AgentSuccessCriteria(
            required_tools=frozenset({"search"}),
            forbidden_tools=frozenset({"delete"}),
            max_steps=4,
        ),
        trajectory,
        task_success=True,
    )
    assert result.task_success
    assert result.efficient
    assert not result.safe
    assert not result.passed
