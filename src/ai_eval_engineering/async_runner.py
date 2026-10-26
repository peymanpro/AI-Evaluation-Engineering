"""Bounded-concurrency execution for asynchronous AI systems."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol, cast

from .budget import BudgetedRunResult, RunBudgetPolicy, _LiveBudgetGuard
from .checkpoint import load_run_checkpoint, save_run_checkpoint
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
from .retry import RetryPolicy, validate_retry_policy_manifest
from .runner import Grader


class AsyncSystemAdapter(Protocol):
    """Contract for an asynchronous system adapter."""

    async def run(self, case: EvaluationCase) -> SystemOutput:
        """Execute one evaluation case asynchronously."""
        ...


class AsyncGrader(Protocol):
    """Contract for graders that perform asynchronous evaluation work."""

    async def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        """Grade one system output asynchronously."""
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
        graders: list[Grader | AsyncGrader],
        *,
        max_concurrency: int = 8,
        timeout_per_case_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
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
        if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
            raise TypeError("retry_policy must be a RetryPolicy or None.")
        self._adapter = adapter
        self._graders: tuple[Grader | AsyncGrader, ...] = tuple(graders)
        self._max_concurrency = max_concurrency
        self._timeout_per_case_seconds = timeout_per_case_seconds
        self._retry_policy = retry_policy

    async def _run_adapter(self, case: EvaluationCase) -> SystemOutput:
        attempts = self._retry_policy.max_attempts if self._retry_policy else 1
        for attempt in range(1, attempts + 1):
            try:
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
                return output
            except Exception as exc:
                if self._retry_policy is None:
                    raise
                delay = self._retry_policy.schedule_retry(case.id, exc, attempt)
                if delay is None:
                    raise
                await asyncio.sleep(delay)
        raise RuntimeError("Async adapter retry loop finished without a result.")

    async def run(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        checkpoint_path: str | Path | None = None,
    ) -> EvaluationRun:
        """Run an asynchronous evaluation, optionally resuming from a checkpoint.

        Checkpoints are written atomically after each completed case. On resume,
        the helper validates the suite fingerprint and run identity before any
        saved result is reused.
        """
        validate_run_inputs(suite, manifest)
        validate_retry_policy_manifest(manifest.configuration, self._retry_policy)
        run_manifest = manifest
        completed: dict[str, CaseResult] = {}
        if checkpoint_path is not None:
            run_manifest, completed = load_run_checkpoint(checkpoint_path, suite, manifest)

        results: list[CaseResult | None] = [None] * len(suite.cases)
        for index, case in enumerate(suite.cases):
            if case.id in completed:
                results[index] = completed[case.id]
        cases = iter(
            (index, case)
            for index, case in enumerate(suite.cases)
            if case.id not in completed
        )
        checkpoint_lock = asyncio.Lock()

        async def worker() -> None:
            while True:
                # next() has no await point, so workers on this event loop take
                # distinct cases before yielding to asynchronous system calls.
                try:
                    index, case = next(cases)
                except StopIteration:
                    return

                output = await self._run_adapter(case)
                validate_system_output(case, output)
                graded_items: list[GraderResult] = []
                for grader in self._graders:
                    grader_result = grader.grade(case, output)
                    if inspect.isawaitable(grader_result):
                        grader_result = await cast(Awaitable[GraderResult], grader_result)
                    if not isinstance(grader_result, GraderResult):
                        raise TypeError("Graders must return GraderResult instances.")
                    graded_items.append(grader_result)
                graded = tuple(graded_items)
                validate_grader_results(graded, case.id)
                case_result = CaseResult(case=case, output=output, graders=graded)
                results[index] = case_result
                if checkpoint_path is not None:
                    async with checkpoint_lock:
                        completed[case.id] = case_result
                        save_run_checkpoint(
                            checkpoint_path, suite, run_manifest, completed
                        )

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
            manifest=run_manifest,
            cases=tuple(cast(CaseResult, result) for result in results),
        )

    async def run_budgeted(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        policy: RunBudgetPolicy,
        checkpoint_path: str | Path | None = None,
    ) -> BudgetedRunResult:
        """Run bounded batches and stop starting new batches at live budget limits.

        Results already in flight are allowed to finish and are included in the
        spend totals. The method never turns a partial run into an EvaluationRun.
        Batch barriers prevent a finished fast worker from starting another case
        while a sibling request from the same batch still has unknown usage.
        """
        validate_run_inputs(suite, manifest)
        validate_retry_policy_manifest(manifest.configuration, self._retry_policy)
        if not isinstance(policy, RunBudgetPolicy):
            raise TypeError("policy must be a RunBudgetPolicy.")

        run_manifest = manifest
        completed: dict[str, CaseResult] = {}
        if checkpoint_path is not None:
            run_manifest, completed = load_run_checkpoint(checkpoint_path, suite, manifest)

        guard = _LiveBudgetGuard(policy)
        results: list[CaseResult | None] = [None] * len(suite.cases)
        todo: list[tuple[int, EvaluationCase]] = []
        for index, case in enumerate(suite.cases):
            saved_result = completed.get(case.id)
            if saved_result is None:
                todo.append((index, case))
                continue
            results[index] = saved_result
            guard.observe_result(saved_result)

        checkpoint_lock = asyncio.Lock()

        async def execute_case(index: int, case: EvaluationCase) -> None:
            output = await self._run_adapter(case)
            validate_system_output(case, output)
            guard.observe_output(case.id, output)

            graded_items: list[GraderResult] = []
            for grader in self._graders:
                grader_result = grader.grade(case, output)
                if inspect.isawaitable(grader_result):
                    grader_result = await cast(Awaitable[GraderResult], grader_result)
                if not isinstance(grader_result, GraderResult):
                    raise TypeError("Graders must return GraderResult instances.")
                graded_items.append(grader_result)
            graded = tuple(graded_items)
            validate_grader_results(graded, case.id)
            case_result = CaseResult(case=case, output=output, graders=graded)
            guard.observe_graders(case_result)
            results[index] = case_result
            completed[case.id] = case_result
            if checkpoint_path is not None:
                async with checkpoint_lock:
                    save_run_checkpoint(
                        checkpoint_path, suite, run_manifest, completed
                    )

        for batch_start in range(0, len(todo), self._max_concurrency):
            if not guard.can_start_case():
                break
            batch = todo[batch_start : batch_start + self._max_concurrency]
            tasks = [
                asyncio.create_task(execute_case(index, case))
                for index, case in batch
            ]
            try:
                await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        ordered_completed = tuple(
            cast(CaseResult, result) for result in results if result is not None
        )
        pending_case_ids = tuple(
            case.id
            for index, case in enumerate(suite.cases)
            if results[index] is None
        )
        status = guard.finish(pending_case_ids)
        return BudgetedRunResult(
            manifest=run_manifest,
            completed_cases=ordered_completed,
            pending_case_ids=pending_case_ids,
            status=status,
            known_cost_usd=guard.known_cost_usd,
            known_tokens=guard.known_tokens,
            stop_reason=guard.stop_reason,
        )

