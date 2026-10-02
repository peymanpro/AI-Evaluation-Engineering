from pathlib import Path

from ai_eval_engineering.cli import EchoAnswerSystem
from ai_eval_engineering.domain import AggregatedResult, EvaluationCase, EvaluationSuite
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.evidence import write_evidence_package
from ai_eval_engineering.report import build_report
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


def test_evidence_package_contains_auditable_inputs(tmp_path: Path) -> None:
    suite = EvaluationSuite("1", (EvaluationCase("a", {"answer": "ok"}, expected="ok"),))
    runner = EvaluationRunner(EchoAnswerSystem(), [ExactMatchGrader()])
    run = runner.run(suite, build_run_metadata(suite, "echo", "1", {"mode": "test"}, seed=1))
    report = build_report(run, AggregatedResult.from_case_results(list(run.cases)))
    root = write_evidence_package(run, report, {"mode": "test"}, tmp_path / "evidence")
    assert (root / "manifest.json").exists()
    assert (root / "raw-results.json").exists()
    assert (root / "configuration.json").exists()
    assert (root / "report.json").exists()
    assert (root / "report.md").exists()
