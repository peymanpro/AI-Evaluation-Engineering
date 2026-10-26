"""Demonstrate bounded-concurrency async evaluation without external services."""

from __future__ import annotations

import asyncio
import json

from ai_eval_engineering import (
    AsyncEvaluationRunner,
    EvaluationCase,
    EvaluationSuite,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


class AsyncEchoSystem:
    """Example async adapter; replace the sleep with an async model/API request."""

    def __init__(self) -> None:
        self.active_requests = 0
        self.max_active_requests = 0

    async def run(self, case: EvaluationCase) -> SystemOutput:
        self.active_requests += 1
        self.max_active_requests = max(self.max_active_requests, self.active_requests)
        try:
            await asyncio.sleep(float(case.input["simulated_latency_seconds"]))
            return SystemOutput(case_id=case.id, output=case.input["answer"])
        finally:
            self.active_requests -= 1


async def main() -> None:
    suite = EvaluationSuite(
        version="async-demo-v1",
        cases=(
            EvaluationCase(
                "slow", {"answer": "correct", "simulated_latency_seconds": 0.04},
                expected="correct",
            ),
            EvaluationCase(
                "fast", {"answer": "correct", "simulated_latency_seconds": 0.001},
                expected="correct",
            ),
            EvaluationCase(
                "medium", {"answer": "wrong", "simulated_latency_seconds": 0.01},
                expected="correct",
            ),
        ),
    )
    system = AsyncEchoSystem()
    runner = AsyncEvaluationRunner(
        system,
        [ExactMatchGrader()],
        max_concurrency=2,
    )
    run = await runner.run(
        suite,
        build_run_metadata(suite, "async-echo", "demo-v1", seed=0),
    )

    print(
        json.dumps(
            {
                "case_order": [item.case.id for item in run.cases],
                "pass_rate": sum(item.graders[0].passed for item in run.cases)
                / len(run.cases),
                "max_concurrent_requests": system.max_active_requests,
                "configured_concurrency": 2,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
