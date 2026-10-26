"""Bounded-concurrency execution for asynchronous AI systems."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol, cast

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
from .execution_report import (
    CaseExecutionResult,
    EvaluationExecutionReport,
    failure_result,
    validate_execution_report,
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

    async def run_report(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        checkpoint_path: str | Path | None = None,
    ) -> EvaluationExecutionReport:
        """Evaluate all cases and capture failures as explicit per-case outcomes.

        A system or grader failure does not cancel unrelated cases. Cancellation
        and checkpoint I/O errors still propagate. Only fully completed cases are
        saved to the resumable checkpoint; failed cases will be retried on resume.
        """
        validate_run_inputs(suite, manifest)
        validate_retry_policy_manifest(manifest.configuration, self._retry_policy)
        run_manifest = manifest
        completed: dict[str, CaseResult] = {}
        if checkpoint_path is not None:
            run_manifest, completed = load_run_checkpoint(checkpoint_path, suite, manifest)

        results: list[CaseExecutionResult | None] = [None] * len(suite.cases)
        for index, case in enumerate(suite.cases):
            saved = completed.get(case.id)
            if saved is not None:
                results[index] = CaseExecutionResult(
                    case=case,
                    status="completed",
                    output=saved.output,
                    graders=saved.graders,
                )

        cases = iter(
            (index, case)
            for index, case in enumerate(suite.cases)
            if case.id not in completed
        )
        checkpoint_lock = asyncio.Lock()

        async def worker() -> None:
            while True:
                try:
                    index, case = next(cases)
                except StopIteration:
                    return

                try:
                    output = await self._run_adapter(case)
                except Exception as exc:  # noqa: BLE001 - adapter and grader exceptions are per-case outcomes
                    results[index] = failure_result(case, "adapter_error", exc)
                    continue

                try:
                    validate_system_output(case, output)
                except Exception as exc:  # noqa: BLE001 - adapter and grader exceptions are per-case outcomes
                    results[index] = failure_result(
                        case, "output_validation_error", exc
                    )
                    continue

                graded: list[GraderResult] = []
                failure_record: CaseExecutionResult | None = None
                for grader in self._graders:
                    try:
                        grader_result = grader.grade(case, output)
                        if inspect.isawaitable(grader_result):
                            grader_result = await cast(
                                Awaitable[GraderResult], grader_result
                            )
                    except Exception as exc:  # noqa: BLE001 - adapter and grader exceptions are per-case outcomes
                        failure_record = failure_result(
                            case,
                            "grader_error",
                            exc,
                            output=output,
                            graders=tuple(graded),
                        )
                        break

                    try:
                        if not isinstance(grader_result, GraderResult):
                            raise TypeError(
                                "Graders must return GraderResult instances."
                            )
                        validate_grader_results((grader_result,), case.id)
                        if any(
                            previous.grader == grader_result.grader
                            for previous in graded
                        ):
                            raise ValueError(
                                f"Duplicate grader name {grader_result.grader!r} "
                                f"for case {case.id!r}."
                            )
                    except Exception as exc:  # noqa: BLE001 - adapter and grader exceptions are per-case outcomes
                        failure_record = failure_result(
                            case,
                            "grader_contract_error",
                            exc,
                            output=output,
                            graders=tuple(graded),
                        )
                        break
                    graded.append(grader_result)

                if failure_record is not None:
                    results[index] = failure_record
                    continue

                graders = tuple(graded)
                case_result = CaseResult(case=case, output=output, graders=graders)
                results[index] = CaseExecutionResult(
                    case=case,
                    status="completed",
                    output=output,
                    graders=graders,
                )
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
            raise RuntimeError(
                "Failure-aware evaluation finished without an outcome for every case."
            )

        report = EvaluationExecutionReport(
            manifest=run_manifest,
            cases=tuple(cast(CaseExecutionResult, result) for result in results),
        )
        validate_execution_report(report)
        return report
