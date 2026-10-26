"""Offline demonstration of per-case failures without fabricating grader scores."""

from __future__ import annotations

import json
from pathlib import Path

from ai_eval_engineering import (
    EvaluationCase,
    EvaluationRunner,
    EvaluationSuite,
    SystemOutput,
    write_execution_report,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


class SyntheticService:
    """A deterministic fixture; this is not a live provider benchmark."""

    def run(self, case: EvaluationCase) -> SystemOutput:
        if case.id == "provider-timeout":
            raise TimeoutError("synthetic timeout fixture")
        return SystemOutput(case.id, case.input["answer"], latency_ms=8.0, cost_usd=0.001)


def main() -> int:
    suite = EvaluationSuite(
        "failure-aware-demo-v1",
        (
            EvaluationCase("happy-path", {"answer": "Paris"}, expected="Paris"),
            EvaluationCase(
                "provider-timeout",
                {"answer": "not executed"},
                expected="not executed",
            ),
            EvaluationCase("last-case", {"answer": "Berlin"}, expected="Berlin"),
        ),
    )
    manifest = build_run_metadata(
        suite,
        "synthetic-service",
        "fixture-1",
        {"fixture": "synthetic", "live_provider_calls": False},
        seed=11,
    )
    report = EvaluationRunner(SyntheticService(), [ExactMatchGrader()]).run_report(
        suite, manifest
    )

    artifact = Path("artifacts") / "failure-aware-execution-report.json"
    write_execution_report(report, artifact)
    print(
        json.dumps(
            {
                "run_id": report.manifest.run_id,
                "is_complete": report.is_complete,
                "completed_count": report.completed_count,
                "failed_count": report.failed_count,
                "cases": [
                    {
                        "case_id": item.case.id,
                        "status": item.status,
                        "failure_stage": item.failure.stage if item.failure else None,
                    }
                    for item in report.cases
                ],
                "report_path": str(artifact),
            },
            indent=2,
            sort_keys=True,
        )
    )
    expected_statuses = ["completed", "adapter_error", "completed"]
    actual_statuses = [item.status for item in report.cases]
    return 0 if actual_statuses == expected_statuses and report.failed_count == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
