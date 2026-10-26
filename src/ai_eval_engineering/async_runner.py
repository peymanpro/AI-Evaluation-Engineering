"""Bounded-concurrency execution for asynchronous AI systems."""

from __future__ import annotations

import asyncio
from typing import cast

from .domain import (
    CaseResult,
    EvaluationRun,
    EvaluationSuite,
    GraderResult,
    SystemOutput,
)
from .runner import Grader


class AsyncSystemAdapter:
    """Protocol-like base contract for asynchronous system adapters.

    Implementations must provide an async `run` method and return the output
    for the supplied case. The runner keeps grading synchronous so existing
    deterministic graders can be reused unchanged.
    """

    async def run(self, case: object) -> SystemOutput:
        """Execute one evaluation case asynchronously."""
        raise NotImplementedError


class AsyncEvaluationRunner:
    """Evaluate cases concurrently while preserving suite order in the result.

    At most `max_concurrency` system calls are in flight at once. Results are
    returned in the original suite order, not completion order. If an adapter
    or grader raises, the run fails fast and pending worker tasks are cancelled;
    partial runs are not returned as if they were complete.
    """

    def __init__(
        self,
        adapter: AsyncSystemAdapter,
        graders: list[Grader],
        *,
        max_concurrency: int = 8,
    ) -> None:
        if not graders:
            raise ValueError("At least one grader is required.")
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise TypeError("max_concurrency must be an integer.")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1.")
        self._adapter = adapter
        self._graders = tuple(graders)
        self._max_concurrency = max_concurrency

    async def run(self, suite: EvaluationSuite, manifest: object) -> EvaluationRun:
        """Run an evaluation suite through an async adapter.

        The manifest is retained as provided, matching the sync runner's
        contract. Adapter calls are bounded; grader methods use the existing
        synchronous `grade(case, output)` interface.
        """
        results: list[CaseResult | None] = [None] * len(suite.cases)
        cases = iter(enumerate(suite.cases))

        async def worker() -> None:
            while True:
                # next() has no await point, so workers on this event loop take
                # distinct cases before yielding to asynchronous system calls.
                try:
                    index, case = next(cases)
                except StopIteration:
                    return

                output = await self._adapter.run(case)
                if not isinstance(output, SystemOutput):
                    raise TypeError(
                        f"System adapter must return SystemOutput for case {case.id!r}."
                    )
                if output.case_id != case.id:
                    raise ValueError(
                        f"System returned case id {output.case_id!r} for expected {case.id!r}."
                    )
                graded: tuple[GraderResult, ...] = tuple(
                    grader.grade(case, output) for grader in self._graders
                )
                results[index] = CaseResult(case=case, output=output, graders=graded)

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(self._max_concurrency, len(suite.cases)))
        ]
        try:
            await asyncio.gather(*workers)
        except BaseException:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise

        if any(result is None for result in results):
            raise RuntimeError("Async evaluation finished without producing every case result.")

        return EvaluationRun(
            manifest=cast("EvaluationRun", object()).manifest
            if False
            else manifest,  # type: ignore[arg-type]
            cases=tuple(cast(CaseResult, result) for result in results),
        )
