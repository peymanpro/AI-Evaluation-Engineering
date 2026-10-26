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
from .execution_report import (
    CaseExecutionResult,
    EvaluationExecutionReport,
    failure_result,
    validate_execution_report,
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

    def run_report(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        checkpoint_path: str | Path | None = None,
    ) -> EvaluationExecutionReport:
        """Run every case and return explicit outcomes instead of failing fast.

        Adapter, output-validation, grader-execution, and grader-contract
        errors are recorded per case and do not become numeric grader scores.
        Successfully completed cases are checkpointed as usual; failed cases
        are retried on a later resume. Checkpoint I/O failures still abort the
        operation because otherwise evidence could be lost silently.
        """
        validate_run_inputs(suite, manifest)
        validate_retry_policy_manifest(manifest.configuration, self._retry_policy)
        run_manifest = manifest
        completed: dict[str, CaseResult] = {}
        if checkpoint_path is not None:
            run_manifest, completed = load_run_checkpoint(checkpoint_path, suite, manifest)

        records: dict[str, CaseExecutionResult] = {}
        for case in suite.cases:
            saved = completed.get(case.id)
            if saved is not None:
                records[case.id] = CaseExecutionResult(
                    case=case,
                    status="completed",
                    output=saved.output,
                    graders=saved.graders,
                )
                continue

            try:
                output = self._run_adapter(case)
            except Exception as exc:  # noqa: BLE001 - adapter and grader exceptions are per-case outcomes
                records[case.id] = failure_result(case, "adapter_error", exc)
                continue

            try:
                validate_system_output(case, output)
            except Exception as exc:  # noqa: BLE001 - adapter and grader exceptions are per-case outcomes
                records[case.id] = failure_result(
                    case, "output_validation_error", exc
                )
                continue

            graded: list[GraderResult] = []
            failure_record: CaseExecutionResult | None = None
            for grader in self._graders:
                try:
                    result = grader.grade(case, output)
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
                    validate_grader_results((result,), case.id)
                    if any(previous.grader == result.grader for previous in graded):
                        raise ValueError(
                            f"Duplicate grader name {result.grader!r} for case {case.id!r}."
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
                graded.append(result)

            if failure_record is not None:
                records[case.id] = failure_record
                continue

            graders = tuple(graded)
            case_result = CaseResult(case=case, output=output, graders=graders)
            completed[case.id] = case_result
            records[case.id] = CaseExecutionResult(
                case=case,
                status="completed",
                output=output,
                graders=graders,
            )
            if checkpoint_path is not None:
                save_run_checkpoint(checkpoint_path, suite, run_manifest, completed)

        report = EvaluationExecutionReport(
            manifest=run_manifest,
            cases=tuple(records[case.id] for case in suite.cases),
        )
        validate_execution_report(report)
        return report


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
