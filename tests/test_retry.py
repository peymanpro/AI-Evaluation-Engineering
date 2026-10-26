from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ai_eval_engineering import (
    AsyncEvaluationRunner,
    EvaluationCase,
    EvaluationRunner,
    EvaluationSuite,
    GraderResult,
    RetryEvent,
    RetryPolicy,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


def make_suite() -> EvaluationSuite:
    return EvaluationSuite(
        "retry-suite-v1",
        (EvaluationCase("case-a", {"question": "test"}, expected="answer"),),
    )


def make_manifest(suite: EvaluationSuite):
    return build_run_metadata(
        suite,
        "retry-test-system",
        "revision-1",
        {"retry_policy": RetryPolicy(max_attempts=2, initial_delay_seconds=0).to_dict()},
        seed=5,
    )


class FlakySyncAdapter:
    def __init__(self, failures: int, error: Exception | None = None) -> None:
        self.failures = failures
        self.error = error or ConnectionError("transient test error")
        self.calls = 0

    def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return SystemOutput(case.id, case.expected)


class AlwaysFailingSyncAdapter:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls += 1
        raise self.error


class FlakyAsyncAdapter:
    def __init__(self, failures: int, error: Exception | None = None) -> None:
        self.failures = failures
        self.error = error or ConnectionError("transient async test error")
        self.calls = 0

    async def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return SystemOutput(case.id, case.expected)


class TimeoutOnceAsyncAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(0.03)
        return SystemOutput(case.id, case.expected)


class FailingGrader:
    def __init__(self) -> None:
        self.calls = 0

    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        self.calls += 1
        raise ConnectionError("grader failure must not trigger adapter retry")


def test_sync_runner_retries_transient_adapter_errors_and_reports_events() -> None:
    suite = make_suite()
    adapter = FlakySyncAdapter(failures=2)
    events: list[RetryEvent] = []
    policy = RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=0,
        on_retry=events.append,
    )

    run = EvaluationRunner(
        adapter,
        [ExactMatchGrader()],
        retry_policy=policy,
    ).run(suite, make_manifest(suite))

    assert adapter.calls == 3
    assert run.cases[0].graders[0].passed
    assert [(event.failed_attempt, event.next_attempt) for event in events] == [(1, 2), (2, 3)]
    assert all(event.case_id == "case-a" for event in events)
    assert all(event.delay_seconds == 0 for event in events)


def test_sync_runner_does_not_retry_non_retryable_exceptions() -> None:
    suite = make_suite()
    adapter = AlwaysFailingSyncAdapter(ValueError("invalid adapter input"))

    with pytest.raises(ValueError, match="invalid adapter input"):
        EvaluationRunner(
            adapter,
            [ExactMatchGrader()],
            retry_policy=RetryPolicy(max_attempts=5, initial_delay_seconds=0),
        ).run(suite, make_manifest(suite))

    assert adapter.calls == 1


def test_sync_runner_does_not_retry_when_policy_is_not_supplied() -> None:
    suite = make_suite()
    adapter = AlwaysFailingSyncAdapter(ConnectionError("network unavailable"))

    with pytest.raises(ConnectionError, match="network unavailable"):
        EvaluationRunner(adapter, [ExactMatchGrader()]).run(suite, make_manifest(suite))

    assert adapter.calls == 1


def test_sync_runner_stops_after_total_attempt_budget_is_exhausted() -> None:
    suite = make_suite()
    adapter = AlwaysFailingSyncAdapter(ConnectionError("still offline"))
    events: list[RetryEvent] = []

    with pytest.raises(ConnectionError, match="still offline"):
        EvaluationRunner(
            adapter,
            [ExactMatchGrader()],
            retry_policy=RetryPolicy(
                max_attempts=2,
                initial_delay_seconds=0,
                on_retry=events.append,
            ),
        ).run(suite, make_manifest(suite))

    assert adapter.calls == 2
    assert len(events) == 1
    assert events[0].failed_attempt == 1


def test_grader_errors_are_not_retried_by_adapter_policy() -> None:
    suite = make_suite()
    adapter = FlakySyncAdapter(failures=0)
    grader = FailingGrader()

    with pytest.raises(ConnectionError, match="grader failure"):
        EvaluationRunner(
            adapter,
            [grader],
            retry_policy=RetryPolicy(max_attempts=3, initial_delay_seconds=0),
        ).run(suite, make_manifest(suite))

    assert adapter.calls == 1
    assert grader.calls == 1


def test_invalid_adapter_output_is_not_retried() -> None:
    suite = make_suite()
    adapter = AlwaysFailingSyncAdapter(ConnectionError("will not be called"))
    adapter.run = lambda case: SystemOutput("wrong-case", "answer")  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="case id"):
        EvaluationRunner(
            adapter,
            [ExactMatchGrader()],
            retry_policy=RetryPolicy(max_attempts=5, initial_delay_seconds=0),
        ).run(suite, make_manifest(suite))

    assert adapter.calls == 0


def test_async_runner_retries_transient_errors_and_preserves_result_order() -> None:
    suite = make_suite()
    adapter = FlakyAsyncAdapter(failures=1)
    events: list[RetryEvent] = []
    runner = AsyncEvaluationRunner(
        adapter,
        [ExactMatchGrader()],
        max_concurrency=2,
        retry_policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0, on_retry=events.append),
    )

    run = asyncio.run(runner.run(suite, make_manifest(suite)))

    assert adapter.calls == 2
    assert [item.case.id for item in run.cases] == ["case-a"]
    assert run.cases[0].graders[0].passed
    assert events[0].exception_type.endswith("ConnectionError")


def test_async_runner_retries_a_per_attempt_deadline_timeout() -> None:
    suite = make_suite()
    adapter = TimeoutOnceAsyncAdapter()
    events: list[RetryEvent] = []
    runner = AsyncEvaluationRunner(
        adapter,
        [ExactMatchGrader()],
        max_concurrency=1,
        timeout_per_case_seconds=0.001,
        retry_policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0, on_retry=events.append),
    )

    run = asyncio.run(runner.run(suite, make_manifest(suite)))

    assert adapter.calls == 2
    assert run.cases[0].graders[0].passed
    assert len(events) == 1
    assert events[0].exception_type.endswith("TimeoutError")


def test_retry_policy_exponential_delay_is_bounded() -> None:
    policy = RetryPolicy(
        max_attempts=5,
        initial_delay_seconds=0.5,
        backoff_factor=3,
        max_delay_seconds=2,
    )

    assert policy.schedule_retry("case-a", ConnectionError(), 1) == pytest.approx(0.5)
    assert policy.schedule_retry("case-a", ConnectionError(), 2) == pytest.approx(1.5)
    assert policy.schedule_retry("case-a", ConnectionError(), 3) == pytest.approx(2.0)
    assert policy.schedule_retry("case-a", ConnectionError(), 4) == pytest.approx(2.0)
    assert policy.schedule_retry("case-a", ConnectionError(), 5) is None
    assert policy.to_dict()["max_attempts"] == 5


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"max_attempts": 0}, ValueError, "at least 1"),
        ({"max_attempts": True}, TypeError, "integer"),
        ({"initial_delay_seconds": -0.1}, ValueError, "non-negative"),
        ({"backoff_factor": 0.5}, ValueError, "at least 1"),
        ({"max_delay_seconds": float("inf")}, ValueError, "finite"),
        ({"retryable_exceptions": (KeyboardInterrupt,)}, TypeError, "Exception subclasses"),
        ({"retryable_exceptions": ()}, ValueError, "non-empty tuple"),
        ({"on_retry": "not callable"}, TypeError, "callable"),
    ],
)
def test_retry_policy_rejects_invalid_configuration(
    kwargs: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        RetryPolicy(**kwargs)
