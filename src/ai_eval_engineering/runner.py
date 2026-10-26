"""Evaluation adapters and deterministic suite execution."""

from __future__ import annotations

import hashlib
import json
import platform
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .budget import BudgetedRunResult, RunBudgetPolicy, _LiveBudgetGuard
from .checkpoint import load_run_checkpoint, save_run_checkpoint
from .contracts import validate_grader_results, validate_run_inputs, validate_system_output
from .domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    GraderResult,
    JsonObject,
    RunMetadata,
    SystemOutput,
)
from .retry import RetryPolicy, validate_retry_policy_manifest


class SystemAdapter(Protocol):
    def run(self, case: EvaluationCase) -> SystemOutput:
        ...


class Grader(Protocol):
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        ...


def configuration_hash(configuration: JsonObject) -> str:
    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def build_run_metadata(
    suite: EvaluationSuite,
    system_name: str,
    system_version: str,
    configuration: JsonObject | None = None,
    seed: int | None = None,
    *,
    retry_policy: RetryPolicy | None = None,
) -> RunMetadata:
    config = dict(configuration or {})
    if retry_policy is not None:
        if not isinstance(retry_policy, RetryPolicy):
            raise TypeError("retry_policy must be a RetryPolicy or None.")
        retry_settings = retry_policy.to_dict()
        if "retry_policy" in config and config["retry_policy"] != retry_settings:
            raise ValueError("configuration.retry_policy does not match retry_policy.")
        config["retry_policy"] = retry_settings
    return RunMetadata(
        run_id=str(uuid.uuid4()),
        suite_version=suite.version,
        system_name=system_name,
        system_version=system_version,
        configuration={**config, "configuration_hash": configuration_hash(config)},
        seed=seed,
        timestamp_utc=datetime.now(UTC).isoformat(),
        environment={"python": platform.python_version(), "platform": platform.platform()},
    )


class EvaluationRunner:
    def __init__(
        self,
        adapter: SystemAdapter,
        graders: list[Grader],
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if not graders:
            raise ValueError("At least one grader is required.")
        if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
            raise TypeError("retry_policy must be a RetryPolicy or None.")
        self._adapter = adapter
        self._graders = graders
        self._retry_policy = retry_policy

    def _run_adapter(self, case: EvaluationCase) -> SystemOutput:
        attempts = self._retry_policy.max_attempts if self._retry_policy else 1
        for attempt in range(1, attempts + 1):
            try:
                return self._adapter.run(case)
            except Exception as exc:
                if self._retry_policy is None:
                    raise
                delay = self._retry_policy.schedule_retry(case.id, exc, attempt)
                if delay is None:
                    raise
                time.sleep(delay)
        raise RuntimeError("Adapter retry loop finished without a result.")

    def run(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        checkpoint_path: str | Path | None = None,
    ) -> EvaluationRun:
        """Run the suite, optionally saving each completed case for later resume.

        When a checkpoint path is supplied, completed cases are written atomically
        after grading. A subsequent invocation validates the suite fingerprint,
        system identity, configuration, and environment before reusing those cases.
        """
        validate_run_inputs(suite, manifest)
        validate_retry_policy_manifest(manifest.configuration, self._retry_policy)
        run_manifest = manifest
        completed: dict[str, CaseResult] = {}
        if checkpoint_path is not None:
            run_manifest, completed = load_run_checkpoint(checkpoint_path, suite, manifest)

        for case in suite.cases:
            if case.id in completed:
                continue
            output = self._run_adapter(case)
            validate_system_output(case, output)
            grader_results = tuple(grader.grade(case, output) for grader in self._graders)
            validate_grader_results(grader_results, case.id)
            completed[case.id] = CaseResult(
                case=case,
                output=output,
                graders=grader_results,
            )
            if checkpoint_path is not None:
                save_run_checkpoint(checkpoint_path, suite, run_manifest, completed)

        return EvaluationRun(
            manifest=run_manifest,
            cases=tuple(completed[case.id] for case in suite.cases),
        )


    def run_budgeted(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        policy: RunBudgetPolicy,
        checkpoint_path: str | Path | None = None,
    ) -> BudgetedRunResult:
        """Run cases until a live budget guard stops scheduling new work.

        This opt-in method can return a partial result when the budget is reached
        or required usage evidence is missing. Partial results are not represented
        as an EvaluationRun. Cost/latency measurements are observed after each
        adapter response; token usage is observed after grading.
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
        for case in suite.cases:
            saved_result = completed.get(case.id)
            if saved_result is not None:
                guard.observe_result(saved_result)

        for case in suite.cases:
            if case.id in completed:
                continue
            if not guard.can_start_case():
                break

            output = self._run_adapter(case)
            validate_system_output(case, output)
            guard.observe_output(case.id, output)
            grader_results = tuple(grader.grade(case, output) for grader in self._graders)
            validate_grader_results(grader_results, case.id)
            case_result = CaseResult(
                case=case,
                output=output,
                graders=grader_results,
            )
            guard.observe_graders(case_result)
            completed[case.id] = case_result
            if checkpoint_path is not None:
                save_run_checkpoint(checkpoint_path, suite, run_manifest, completed)

        ordered_completed = tuple(
            completed[case.id] for case in suite.cases if case.id in completed
        )
        pending_case_ids = tuple(
            case.id for case in suite.cases if case.id not in completed
        )
        status = guard.finish(
            pending_case_ids, completed_case_count=len(ordered_completed)
        )
        return BudgetedRunResult(
            manifest=run_manifest,
            completed_cases=ordered_completed,
            pending_case_ids=pending_case_ids,
            status=status,
            known_cost_usd=guard.known_cost_usd,
            known_tokens=guard.known_tokens,
            stop_reason=guard.stop_reason,
        )


def persist_run(run: EvaluationRun, path: str | Path) -> None:
    payload = {
        "manifest": _jsonify(run.manifest),
        "cases": [_jsonify(result) for result in run.cases],
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _jsonify(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonify(field) for key, field in vars(value).items()}
    if isinstance(value, tuple):
        return [_jsonify(item) for item in value]
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    return value
