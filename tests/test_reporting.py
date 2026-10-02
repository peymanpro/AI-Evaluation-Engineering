from ai_eval_engineering.cli import EchoAnswerSystem
from ai_eval_engineering.domain import AggregatedResult, EvaluationCase, EvaluationSuite
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.report import build_report, render_markdown
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


def test_report_contains_failure_taxonomy() -> None:
    suite = EvaluationSuite(
        "1",
        (
            EvaluationCase("pass", {"answer": "ok"}, expected="ok"),
            EvaluationCase(
                "fail",
                {"answer": "bad"},
                expected="ok",
                risk_category="correctness",
            ),
        ),
    )
    run = EvaluationRunner(EchoAnswerSystem(), [ExactMatchGrader()]).run(
        suite,
        build_run_metadata(suite, "echo", "1", seed=1),
    )
    report = build_report(run, AggregatedResult.from_case_results(list(run.cases)))
    assert report["failure_taxonomy"] == {"correctness": 1}
    assert "Failure Taxonomy" in render_markdown(report)
