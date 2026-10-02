"""Command-line demonstration of the evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

from .domain import AggregatedResult, EvaluationCase, EvaluationSuite, SystemOutput
from .graders import ExactMatchGrader
from .report import build_report, write_json_report, write_markdown_report
from .regression import BaselineRecord, RegressionRule, evaluate_gate
from .runner import EvaluationRunner, build_run_metadata
from .statistics import bootstrap_mean_ci


class EchoAnswerSystem:
    def run(self, case: EvaluationCase) -> SystemOutput:
        return SystemOutput(case_id=case.id, output=case.input["answer"])


def main() -> None:
    suite = EvaluationSuite(
        version="demo-1",
        cases=(
            EvaluationCase("case-1", {"answer": "Paris"}, expected="Paris"),
            EvaluationCase("case-2", {"answer": "4"}, expected="4"),
            EvaluationCase("case-3", {"answer": "Berlin"}, expected="Berlin"),
        ),
    )
    runner = EvaluationRunner(EchoAnswerSystem(), [ExactMatchGrader()])
    manifest = build_run_metadata(
        suite, "echo-answer", "1.0.0", {"mode": "deterministic"}, seed=7
    )
    run = runner.run(suite, manifest)
    aggregate = AggregatedResult.from_case_results(list(run.cases))
    ci = bootstrap_mean_ci(list(aggregate.scores), seed=manifest.seed or 0)
    gate = evaluate_gate(
        BaselineRecord("demo-1", "0.9.0", {"pass_rate": 1.0}),
        {"pass_rate": aggregate.pass_rate},
        [RegressionRule("pass_rate", 0.0)],
    )
    report = build_report(run, aggregate, confidence_interval=ci, gate=gate)

    output_dir = Path("artifacts")
    output_dir.mkdir(exist_ok=True)
    write_json_report(report, output_dir / "demo-report.json")
    write_markdown_report(report, output_dir / "demo-report.md")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
