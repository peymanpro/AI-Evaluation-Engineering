from __future__ import annotations

import asyncio

import pytest

from ai_eval_engineering.async_runner import AsyncEvaluationRunner
from ai_eval_engineering.domain import (
    EvaluationCase,
    EvaluationSuite,
    RunMetadata,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


class DelayedEchoAdapter:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def run(self, case: EvaluationCase) -> SystemOutput:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(float(case.input["delay"]))
            return SystemOutput(case.id, case.input["answer"])
        finally:
            self.active -= 1


class WrongIdAdapter:
    async def run(self, case: EvaluationCase) -> SystemOutput:
        await asyncio.sleep(0)
        return SystemOutput("wrong-id", case.input)


class SlowAndFailingAdapter:
    def __init__(self) -> None:
        self.slow_cancelled = False

    async def run(self, case: EvaluationCase) -> SystemOutput:
        if case.id == "broken":
            await asyncio.sleep(0)
            return SystemOutput("wrong-id", None)
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.slow_cancelled = True
            raise
        return SystemOutput(case.id, None)


def make_suite() -> EvaluationSuite:
    return EvaluationSuite(
        "suite-v1",
        (
            EvaluationCase("slow", {"answer": "slow", "delay": 0.04}, expected="slow"),
            EvaluationCase("fast", {"answer": "fast", "delay": 0.001}, expected="fast"),
            EvaluationCase("middle", {"answer": "middle", "delay": 0.01}, expected="middle"),
            EvaluationCase("last", {"answer": "last", "delay": 0.001}, expected="last"),
        ),
    )


def manifest_for(suite: EvaluationSuite) -> RunMetadata:
    return build_run_metadata(suite, "async-echo", "test", seed=7)


def test_async_runner_bounds_concurrency_and_preserves_suite_order() -> None:
    suite = make_suite()
    adapter = DelayedEchoAdapter()
    runner = AsyncEvaluationRunner(adapter, [ExactMatchGrader()], max_concurrency=2)

    run = asyncio.run(runner.run(suite, manifest_for(suite)))

    assert tuple(result.case.id for result in run.cases) == tuple(
        case.id for case in suite.cases
    )
    assert all(result.graders[0].passed for result in run.cases)
    assert 1 < adapter.max_active <= 2
    assert run.manifest.suite_version == suite.version


@pytest.mark.parametrize(
    ("value", "error", "message"),
    [
        (True, TypeError, "integer"),
        (1.5, TypeError, "integer"),
        (0, ValueError, "at least 1"),
        (-2, ValueError, "at least 1"),
    ],
)
def test_async_runner_rejects_invalid_concurrency(
    value: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        AsyncEvaluationRunner(DelayedEchoAdapter(), [ExactMatchGrader()], max_concurrency=value)  # type: ignore[arg-type]


def test_async_runner_requires_at_least_one_grader() -> None:
    with pytest.raises(ValueError, match="At least one grader"):
        AsyncEvaluationRunner(DelayedEchoAdapter(), [])


def test_async_runner_accepts_an_empty_suite() -> None:
    suite = EvaluationSuite("empty-v1", ())
    run = asyncio.run(
        AsyncEvaluationRunner(DelayedEchoAdapter(), [ExactMatchGrader()]).run(
            suite, manifest_for(suite)
        )
    )
    assert run.cases == ()


def test_async_runner_rejects_mismatched_case_id() -> None:
    suite = EvaluationSuite("suite-v1", (EvaluationCase("case-a", {}, expected=None),))
    runner = AsyncEvaluationRunner(WrongIdAdapter(), [ExactMatchGrader()])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="expected 'case-a'"):
        asyncio.run(runner.run(suite, manifest_for(suite)))


def test_async_runner_cancels_other_workers_on_failure() -> None:
    suite = EvaluationSuite(
        "suite-v1",
        (
            EvaluationCase("broken", {}),
            EvaluationCase("slow", {}),
        ),
    )
    adapter = SlowAndFailingAdapter()
    runner = AsyncEvaluationRunner(adapter, [ExactMatchGrader()], max_concurrency=2)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="expected 'broken'"):
        asyncio.run(runner.run(suite, manifest_for(suite)))

    assert adapter.slow_cancelled is True
