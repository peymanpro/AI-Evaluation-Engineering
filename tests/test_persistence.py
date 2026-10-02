from ai_eval_engineering.domain import AggregatedResult, EvaluationCase, EvaluationSuite, SystemOutput
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata, persist_run


class EchoSystem:
    def run(self, case: EvaluationCase) -> SystemOutput:
        return SystemOutput(case.id, case.expected)


def test_run_persistence_contains_manifest_and_case_evidence(tmp_path) -> None:
    suite = EvaluationSuite("v1", (EvaluationCase("a", {}, expected="ok"),))
    run = EvaluationRunner(EchoSystem(), [ExactMatchGrader()]).run(
        suite, build_run_metadata(suite, "echo", "1.0", {"prompt": "baseline"}, seed=1)
    )
    path = tmp_path / "run.json"
    persist_run(run, path)
    payload = path.read_text(encoding="utf-8")
    assert '"system_name": "echo"' in payload
    assert '"grader": "exact_match"' in payload
    assert AggregatedResult.from_case_results(list(run.cases)).pass_rate == 1.0
