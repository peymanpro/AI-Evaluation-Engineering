"""Bounded-concurrency execution for asynchronous AI systems."""

from __future__ import annotations

import asyncio
import math
from typing import Protocol, cast

from .contracts import validate_grader_results, validate_run_inputs, validate_system_output
from .domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from .runner import Grader


class AsyncSystemAdapter(Protocol):
    """Contract for an asynchronous system adapter."""

    async def run(self, case: EvaluationCase) -> SystemOutput:
        """Execute one evaluation case asynchronously."""
        ...


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
        timeout_per_case_seconds: float | None = None,
    ) -> None:
        if not graders:
            raise ValueError("At least one grader is required.")
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise TypeError("max_concurrency must be an integer.")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1.")
        if timeout_per_case_seconds is not None:
            if isinstance(timeout_per_case_seconds, bool) or not isinstance(
                timeout_per_case_seconds, (int, float)
            ):
                raise TypeError("timeout_per_case_seconds must be numeric or None.")
            try:
                timeout_value = float(timeout_per_case_seconds)
            except OverflowError as exc:
                raise ValueError("timeout_per_case_seconds must be finite and positive.") from exc
            if not math.isfinite(timeout_value) or timeout_value <= 0:
                raise ValueError("timeout_per_case_seconds must be finite and positive.")
            timeout_per_case_seconds = timeout_value
        self._adapter = adapter
        self._graders = tuple(graders)
        self._max_concurrency = max_concurrency
        self._timeout_per_case_seconds = timeout_per_case_seconds

    async def run(self, suite: EvaluationSuite, manifest: RunMetadata) -> EvaluationRun:
        """Run an evaluation suite through an async adapter.

        The manifest is retained as provided, matching the sync runner's
        contract. Adapter calls are bounded; grader methods use the existing
        synchronous `grade(case, output)` interface.
        """
        validate_run_inputs(suite, manifest)
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

                timeout_seconds = self._timeout_per_case_seconds
                if timeout_seconds is None:
                    output = await self._adapter.run(case)
                else:
                    timeout_scope = asyncio.timeout(timeout_seconds)
                    try:
                        async with timeout_scope:
                            output = await self._adapter.run(case)
                    except TimeoutError as exc:
                        if timeout_scope.expired():
                            raise TimeoutError(
                                f"System adapter timed out for case {case.id!r} after "
                                f"{timeout_seconds:g} seconds."
                            ) from exc
                        raise
                validate_system_output(case, output)
                graded: tuple[GraderResult, ...] = tuple(
                    grader.grade(case, output) for grader in self._graders
                )
                validate_grader_results(graded, case.id)
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
            manifest=manifest,
            cases=tuple(cast(CaseResult, result) for result in results),
        )
