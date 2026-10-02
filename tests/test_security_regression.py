from pathlib import Path

from ai_eval_engineering.dataset import load_suite
from ai_eval_engineering.domain import EvaluationCase, SystemOutput
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


class SafeFixtureSystem:
    def run(self, case: EvaluationCase) -> SystemOutput:
        return SystemOutput(case.id, "refuse")


def test_adversarial_cases_are_executable_regressions() -> None:
    suite = load_suite(Path("data/adversarial.json"))
    run = EvaluationRunner(SafeFixtureSystem(), [ExactMatchGrader()]).run(
        suite,
        build_run_metadata(suite, "safe-fixture", "1.0.0", seed=0),
    )
    assert len(run.cases) == 3
    assert all(
        grader.passed
        for result in run.cases
        for grader in result.graders
    )
