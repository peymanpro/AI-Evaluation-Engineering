from ai_eval_engineering.domain import EvaluationCase, SystemOutput
from ai_eval_engineering.graders import ExactMatchGrader, TrajectoryGrader


def test_exact_match_normalizes_text() -> None:
    case = EvaluationCase("a", {}, expected=" Hello   World ")
    output = SystemOutput("a", "hello world")
    assert ExactMatchGrader().grade(case, output).passed


def test_trajectory_grader_detects_forbidden_and_excessive_steps() -> None:
    case = EvaluationCase("a", {}, expected=None)
    output = SystemOutput(
        "a",
        "done",
        trace=[
            {"tool_name": "search"},
            {"tool_name": "delete"},
            {"tool_name": "delete"},
        ],
    )
    result = TrajectoryGrader(forbidden_tools={"delete"}, max_steps=2).grade(case, output)
    assert not result.passed
    assert "forbidden" in result.details
    assert "max is 2" in result.details
