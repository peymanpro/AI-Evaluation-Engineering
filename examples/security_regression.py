"""Run the compact adversarial regression suite without a network dependency."""
from __future__ import annotations

import json
from pathlib import Path

from ai_eval_engineering.dataset import load_suite
from ai_eval_engineering.domain import EvaluationCase, SystemOutput
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


class SafeFixtureSystem:
    def run(self, case: EvaluationCase) -> SystemOutput:
        return SystemOutput(case.id, "refuse")


def main() -> None:
    suite = load_suite(Path("data/adversarial.json"))
    runner = EvaluationRunner(SafeFixtureSystem(), [ExactMatchGrader()])
    run = runner.run(
        suite,
        build_run_metadata(
            suite, "safe-fixture", "1.0.0", {"mode": "security-regression"}, seed=0
        ),
    )
    passed = sum(
        all(grader.passed for grader in result.graders)
        for result in run.cases
    )
    print(
        json.dumps(
            {
                "suite": suite.version,
                "passed_cases": passed,
                "total_cases": len(suite.cases),
                "status": "passed" if passed == len(suite.cases) else "failed",
            },
            indent=2,
        )
    )
    if passed != len(suite.cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
