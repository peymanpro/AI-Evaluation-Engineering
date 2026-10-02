from ai_eval_engineering.domain import (
    AggregatedResult,
    EvaluationCase,
    EvaluationSuite,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader, Rule, RuleBasedGrader, SchemaGrader
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


class EchoSystem:
    def run(self, case: EvaluationCase) -> SystemOutput:
        return SystemOutput(case_id=case.id, output=case.input["value"])


def test_case_and_suite_are_typed() -> None:
    suite = EvaluationSuite(
        version="1",
        cases=(EvaluationCase("a", {"value": "ok"}, expected="ok"),),
    )
    assert suite.version == "1"
    assert suite.cases[0].id == "a"


def test_runner_collects_case_results() -> None:
    suite = EvaluationSuite(
        version="1",
        cases=(EvaluationCase("a", {"value": "ok"}, expected="ok"),),
    )
    runner = EvaluationRunner(EchoSystem(), [ExactMatchGrader()])
    run = runner.run(suite, build_run_metadata(suite, "echo", "1", {"mode": "test"}, seed=1))
    aggregate = AggregatedResult.from_case_results(list(run.cases))
    assert aggregate.total_cases == 1
    assert aggregate.pass_rate == 1.0


def test_rule_and_schema_graders() -> None:
    case = EvaluationCase("a", {}, expected=None)
    output = SystemOutput("a", {"answer": "ok", "score": 1})
    schema = SchemaGrader(
        {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
    )
    rules = RuleBasedGrader(
        [Rule("nonempty", lambda _, o: bool(o.output["answer"]), "answer empty")]
    )
    assert schema.grade(case, output).passed
    assert rules.grade(case, output).passed
