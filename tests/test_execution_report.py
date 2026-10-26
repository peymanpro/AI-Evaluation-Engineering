from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import pytest

import ai_eval_engineering as public_api
from ai_eval_engineering import (
    AsyncEvaluationRunner,
    EvaluationRunner,
    EvaluationSuite,
    ExecutionReportError,
    GraderResult,
    SystemOutput,
    export_execution_report,
    import_execution_report_payload,
    load_execution_report,
    write_execution_report,
)
from ai_eval_engineering.domain import EvaluationCase
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


def make_suite() -> EvaluationSuite:
    return EvaluationSuite(
        "failure-aware-v1",
        (
            EvaluationCase("first", {"prompt": "first"}, expected="answer-first", tags=("smoke",)),
            EvaluationCase("fails", {"prompt": "fails"}, expected="answer-fails", tags=("smoke",)),
            EvaluationCase("last", {"prompt": "last"}, expected="answer-last", tags=("regression",)),
        ),
    )


def make_manifest(suite: EvaluationSuite):
    return build_run_metadata(
        suite,
        "failure-aware-test-system",
        "revision-1",
        {"fixture": "synthetic"},
        seed=23,
    )


class SelectiveSyncAdapter:
    def __init__(self, failing_case: str | None = "fails") -> None:
        self.failing_case = failing_case
        self.calls: list[str] = []

    def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls.append(case.id)
        if case.id == self.failing_case:
            raise ConnectionError(f"synthetic adapter failure for {case.id}")
        return SystemOutput(
            case_id=case.id,
            output=case.expected,
            latency_ms=4.0,
            cost_usd=0.002,
        )


class SelectiveAsyncAdapter:
    def __init__(self, failing_case: str | None = "fails") -> None:
        self.failing_case = failing_case
        self.calls: list[str] = []

    async def run(self, case: EvaluationCase) -> SystemOutput:
        await asyncio.sleep(0)
        self.calls.append(case.id)
        if case.id == self.failing_case:
            raise TimeoutError(f"synthetic adapter timeout for {case.id}")
        return SystemOutput(case.id, case.expected, latency_ms=3.0, cost_usd=0.001)


class ExplodingGrader:
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        if case.id == "fails":
            raise RuntimeError("synthetic grader failure")
        return GraderResult("exploding", True, 1.0, "completed")


class InvalidScoreGrader:
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        return GraderResult("invalid-score", True, float("nan"), "not valid evidence")


class WrongCaseIdAdapter:
    def run(self, case: EvaluationCase) -> SystemOutput:
        return SystemOutput("unexpected-case-id", case.expected)


class AlwaysFailingSemanticGrader:
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        return GraderResult("semantic-check", False, 0.0, "valid negative result")


def test_sync_run_report_continues_after_adapter_failure_without_zero_score() -> None:
    suite = make_suite()
    adapter = SelectiveSyncAdapter()
    report = EvaluationRunner(adapter, [ExactMatchGrader()]).run_report(
        suite, make_manifest(suite)
    )

    assert [case.case.id for case in report.cases] == ["first", "fails", "last"]
    assert [case.status for case in report.cases] == [
        "completed",
        "adapter_error",
        "completed",
    ]
    assert report.completed_count == 2
    assert report.failed_count == 1
    assert not report.is_complete
    failed = report.cases[1]
    assert failed.output is None
    assert failed.graders == ()
    assert failed.failure is not None
    assert failed.failure.stage == "adapter"
    assert failed.failure.exception_type.endswith("ConnectionError")
    assert "synthetic adapter failure" in failed.failure.message
    assert adapter.calls == ["first", "fails", "last"]

    with pytest.raises(ExecutionReportError, match="failed cases"):
        report.to_evaluation_run()


def test_grader_exception_preserves_output_and_prior_grader_results() -> None:
    suite = make_suite()
    report = EvaluationRunner(
        SelectiveSyncAdapter(failing_case=None),
        [ExactMatchGrader(), ExplodingGrader()],
    ).run_report(suite, make_manifest(suite))

    failed = report.cases[1]
    assert failed.status == "grader_error"
    assert failed.output is not None
    assert failed.output.case_id == "fails"
    assert [grader.grader for grader in failed.graders] == ["exact_match"]
    assert failed.failure is not None
    assert failed.failure.stage == "grader_execution"
    assert "synthetic grader failure" in failed.failure.message
    assert report.failed_count == 1
    assert report.cases[2].status == "completed"


def test_output_validation_failure_is_explicit_and_does_not_keep_invalid_output() -> None:
    suite = make_suite()
    report = EvaluationRunner(
        WrongCaseIdAdapter(),
        [ExactMatchGrader()],
    ).run_report(suite, make_manifest(suite))

    item = report.cases[0]
    assert item.status == "output_validation_error"
    assert item.output is None
    assert item.graders == ()
    assert item.failure is not None
    assert item.failure.stage == "output_validation"
    assert "case id" in item.failure.message


def test_invalid_grader_contract_is_reported_separately() -> None:
    suite = make_suite()
    report = EvaluationRunner(
        SelectiveSyncAdapter(failing_case=None),
        [InvalidScoreGrader()],
    ).run_report(suite, make_manifest(suite))

    item = report.cases[0]
    assert item.status == "grader_contract_error"
    assert item.output is not None
    assert item.graders == ()
    assert item.failure is not None
    assert item.failure.stage == "grader_contract"
    assert "finite" in item.failure.message


def test_semantic_grader_failure_is_still_a_completed_execution() -> None:
    suite = EvaluationSuite(
        "semantic-failure-v1",
        (EvaluationCase("one", {"prompt": "one"}, expected="answer"),),
    )
    report = EvaluationRunner(
        SelectiveSyncAdapter(failing_case=None),
        [AlwaysFailingSemanticGrader()],
    ).run_report(suite, make_manifest(suite))

    assert report.is_complete
    assert report.failed_count == 0
    run = report.to_evaluation_run()
    assert run.cases[0].graders[0].passed is False
    assert run.cases[0].graders[0].score == 0.0


def test_async_run_report_continues_after_failure_and_preserves_suite_order() -> None:
    suite = make_suite()
    adapter = SelectiveAsyncAdapter()
    runner = AsyncEvaluationRunner(
        adapter,
        [ExactMatchGrader()],
        max_concurrency=3,
    )
    report = asyncio.run(runner.run_report(suite, make_manifest(suite)))

    assert [case.case.id for case in report.cases] == ["first", "fails", "last"]
    assert [case.status for case in report.cases] == [
        "completed",
        "adapter_error",
        "completed",
    ]
    assert report.failed_count == 1
    assert adapter.calls == ["first", "fails", "last"] or set(adapter.calls) == {
        "first", "fails", "last"
    }


def test_run_report_checkpoint_reuses_successful_cases_and_retries_failed_case(
    tmp_path: Path,
) -> None:
    suite = make_suite()
    checkpoint = tmp_path / "nested" / "resume.json"
    first_adapter = SelectiveSyncAdapter()
    first_report = EvaluationRunner(first_adapter, [ExactMatchGrader()]).run_report(
        suite, make_manifest(suite), checkpoint_path=checkpoint
    )

    assert [item.status for item in first_report.cases] == [
        "completed", "adapter_error", "completed"
    ]
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert [row["case"]["id"] for row in saved["run"]["cases"]] == ["first", "last"]

    resume_adapter = SelectiveSyncAdapter(failing_case=None)
    resumed = EvaluationRunner(resume_adapter, [ExactMatchGrader()]).run_report(
        suite, make_manifest(suite), checkpoint_path=checkpoint
    )
    assert resumed.is_complete
    assert [item.case.id for item in resumed.cases] == ["first", "fails", "last"]
    assert resume_adapter.calls == ["fails"]


def test_execution_report_json_round_trip_is_atomic_and_loadable(tmp_path: Path) -> None:
    suite = make_suite()
    report = EvaluationRunner(
        SelectiveSyncAdapter(),
        [ExactMatchGrader()],
    ).run_report(suite, make_manifest(suite))
    path = tmp_path / "nested" / "execution-report.json"

    assert write_execution_report(report, path) == path
    assert load_execution_report(path) == report
    assert import_execution_report_payload(export_execution_report(report)) == report
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_execution_report_rejects_unknown_contract_fields() -> None:
    suite = make_suite()
    report = EvaluationRunner(
        SelectiveSyncAdapter(), [ExactMatchGrader()]
    ).run_report(suite, make_manifest(suite))
    payload = copy.deepcopy(export_execution_report(report))
    payload["cases"][0]["unexpected"] = "cannot be silently discarded"

    with pytest.raises(ExecutionReportError, match="unsupported fields: unexpected"):
        import_execution_report_payload(payload)


def test_execution_report_rejects_status_failure_mismatch() -> None:
    suite = make_suite()
    report = EvaluationRunner(
        SelectiveSyncAdapter(), [ExactMatchGrader()]
    ).run_report(suite, make_manifest(suite))
    payload = export_execution_report(report)
    payload["cases"][0]["status"] = "adapter_error"

    with pytest.raises(TypeError, match="failure is required"):
        import_execution_report_payload(payload)


def test_packaged_execution_report_schema_matches_repository_copy() -> None:
    schema = public_api.get_execution_report_schema()
    repository_schema_path = (
        Path(__file__).parents[1] / "schemas" / "execution-report-v1.schema.json"
    )
    repository_schema = json.loads(repository_schema_path.read_text(encoding="utf-8"))

    assert schema == repository_schema
    assert schema["properties"]["schema_version"]["const"] == 1
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["caseExecution"]["additionalProperties"] is False
    assert schema["$defs"]["jsonObject"]["additionalProperties"]["$ref"] == (
        "#/$defs/jsonValue"
    )
