"""Demonstrate opt-in adapter retries without making provider calls."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from ai_eval_engineering import (
    AsyncEvaluationRunner,
    EvaluationCase,
    EvaluationRunner,
    EvaluationSuite,
    RetryEvent,
    RetryPolicy,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


class FlakySyncSystem:
    """Simulate one transient transport failure before returning a result."""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("simulated connection failure")
        return SystemOutput(case.id, case.expected)


class FlakyAsyncSystem:
    """Async variant of the same deterministic scenario."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("simulated timeout")
        return SystemOutput(case.id, case.expected)


async def main() -> int:
    suite = EvaluationSuite(
        "retry-demo-v1",
        (EvaluationCase("case-1", {"task": "answer"}, expected="answer"),),
    )
    sync_events: list[RetryEvent] = []
    sync_policy = RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=0,
        on_retry=sync_events.append,
    )
    sync_system = FlakySyncSystem()
    sync_run = EvaluationRunner(
        sync_system,
        [ExactMatchGrader()],
        retry_policy=sync_policy,
    ).run(
        suite,
        build_run_metadata(
            suite,
            "flaky-sync-demo",
            "demo-v1",
            retry_policy=sync_policy,
        ),
    )

    async_events: list[RetryEvent] = []
    async_policy = RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=0,
        on_retry=async_events.append,
    )
    async_system = FlakyAsyncSystem()
    async_run = await AsyncEvaluationRunner(
        async_system,
        [ExactMatchGrader()],
        max_concurrency=2,
        retry_policy=async_policy,
    ).run(
        suite,
        build_run_metadata(
            suite,
            "flaky-async-demo",
            "demo-v1",
            retry_policy=async_policy,
        ),
    )

    summary = {
        "sync": {
            "adapter_calls": sync_system.calls,
            "passed": sync_run.cases[0].graders[0].passed,
            "retry_events": [asdict(event) for event in sync_events],
            "recorded_policy": sync_run.manifest.configuration["retry_policy"],
        },
        "async": {
            "adapter_calls": async_system.calls,
            "passed": async_run.cases[0].graders[0].passed,
            "retry_events": [asdict(event) for event in async_events],
            "recorded_policy": async_run.manifest.configuration["retry_policy"],
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if (
        sync_system.calls == 2
        and async_system.calls == 2
        and sync_run.cases[0].graders[0].passed
        and async_run.cases[0].graders[0].passed
    ) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
