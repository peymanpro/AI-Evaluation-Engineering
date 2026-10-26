from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from ai_eval_engineering.async_runner import AsyncEvaluationRunner
from ai_eval_engineering.contracts import validate_run_inputs, validate_suite
from ai_eval_engineering.domain import (
    EvaluationCase,
    EvaluationSuite,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import EvaluationRunner, build_run_metadata


class CountingSystem:
    def __init__(self, output: SystemOutput | None = None) -> None:
        self.calls = 0
        self.output = output

    def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls += 1
        return self.output or SystemOutput(case.id, case.expected)


class AsyncCountingSystem:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls += 1
        return SystemOutput(case.id, case.expected)


class FixedGrader:
    def __init__(self, results: tuple[GraderResult, ...]) -> None:
        self.results = results

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        return self.results[0]


def suite_with(*cases: EvaluationCase) -> EvaluationSuite:
    return EvaluationSuite("suite-v1", tuple(cases))


def manifest_for(suite: EvaluationSuite) -> RunMetadata:
    return build_run_metadata(suite, "contract-test-system", "git:test")


def test_suite_rejects_duplicate_ids_before_system_execution() -> None:
    suite = suite_with(EvaluationCase("duplicate", {}), EvaluationCase("duplicate", {}))
    system = CountingSystem()
    runner = EvaluationRunner(system, [ExactMatchGrader()])

    with pytest.raises(ValueError, match="Duplicate case id 'duplicate'"):
        runner.run(suite, manifest_for(suite))

    assert system.calls == 0


def test_run_manifest_must_identify_the_actual_suite() -> None:
    suite = suite_with(EvaluationCase("case-a", {}))
    system = CountingSystem()
    runner = EvaluationRunner(system, [ExactMatchGrader()])
    wrong_manifest = replace(manifest_for(suite), suite_version="old-suite-v0")

    with pytest.raises(ValueError, match="does not match suite.version"):
        runner.run(suite, wrong_manifest)

    assert system.calls == 0


def test_preflight_rejects_non_finite_case_values() -> None:
    suite = suite_with(EvaluationCase("bad", {"temperature": float("nan")}))

    with pytest.raises(ValueError, match="non-finite"):
        validate_suite(suite)


def test_preflight_rejects_circular_case_data() -> None:
    payload: dict[str, object] = {}
    payload["self"] = payload
    suite = suite_with(EvaluationCase("circular", payload))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="circular reference"):
        validate_suite(suite)


def test_preflight_rejects_mismatched_manifest_for_async_runner() -> None:
    suite = suite_with(EvaluationCase("case-a", {}))
    system = AsyncCountingSystem()
    runner = AsyncEvaluationRunner(system, [ExactMatchGrader()])
    wrong_manifest = replace(manifest_for(suite), suite_version="old-suite-v0")

    with pytest.raises(ValueError, match="does not match suite.version"):
        asyncio.run(runner.run(suite, wrong_manifest))

    assert system.calls == 0


def test_runner_rejects_non_finite_output_latency() -> None:
    suite = suite_with(EvaluationCase("case-a", {}))
    bad_output = SystemOutput("case-a", "answer", latency_ms=float("inf"))
    system = CountingSystem(bad_output)
    runner = EvaluationRunner(system, [ExactMatchGrader()])

    with pytest.raises(ValueError, match="latency_ms.*finite"):
        runner.run(suite, manifest_for(suite))

    assert system.calls == 1


def test_runner_rejects_duplicate_grader_names() -> None:
    suite = suite_with(EvaluationCase("case-a", {}, expected="answer"))
    system = CountingSystem()
    duplicate = GraderResult("duplicate", True, 1.0, "ok")
    runner = EvaluationRunner(
        system,
        [FixedGrader((duplicate,)), FixedGrader((duplicate,))],
    )

    with pytest.raises(ValueError, match="Duplicate grader name 'duplicate'"):
        runner.run(suite, manifest_for(suite))


def test_runner_rejects_non_finite_grader_scores() -> None:
    suite = suite_with(EvaluationCase("case-a", {}))
    system = CountingSystem()
    bad_grader = FixedGrader((GraderResult("bad", False, float("nan"), "invalid"),))
    runner = EvaluationRunner(system, [bad_grader])

    with pytest.raises(ValueError, match="score.*finite"):
        runner.run(suite, manifest_for(suite))


def test_run_input_validator_accepts_a_consistent_empty_suite() -> None:
    suite = EvaluationSuite("empty-v1", ())
    validate_run_inputs(suite, manifest_for(suite))
