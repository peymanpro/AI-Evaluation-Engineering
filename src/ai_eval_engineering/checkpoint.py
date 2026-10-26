"""Atomic, fingerprinted checkpoints for resumable evaluation runs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .contracts import validate_grader_results, validate_system_output
from .domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    RunMetadata,
)
from .result_import import export_run_payload, import_run_payload

_CHECKPOINT_VERSION = 1


class CheckpointError(ValueError):
    """A checkpoint is malformed or does not match the requested evaluation."""


def load_run_checkpoint(
    path: str | Path,
    suite: EvaluationSuite,
    requested_manifest: RunMetadata,
) -> tuple[RunMetadata, dict[str, CaseResult]]:
    """Load and validate previously completed cases for a matching evaluation.

    A missing file starts a new checkpointed run. An existing but incompatible
    or corrupt file raises CheckpointError instead of silently discarding work
    or reusing evidence from a different suite/system configuration.
    """
    target = Path(path)
    if not target.exists():
        return requested_manifest, {}

    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"Could not read run checkpoint at {target}.") from exc

    if not isinstance(payload, dict) or set(payload) != {
        "checkpoint_version",
        "suite_fingerprint",
        "run",
    }:
        raise CheckpointError("Checkpoint root must contain only version, fingerprint, and run.")
    version = payload.get("checkpoint_version")
    if isinstance(version, bool) or version != _CHECKPOINT_VERSION:
        raise CheckpointError(
            f"Unsupported checkpoint version {version!r}; expected {_CHECKPOINT_VERSION}."
        )
    expected_fingerprint = _suite_fingerprint(suite)
    if payload.get("suite_fingerprint") != expected_fingerprint:
        raise CheckpointError(
            "Current suite definitions do not match the checkpoint fingerprint. "
            "Use the original suite or a new checkpoint path."
        )

    run_payload = payload.get("run")
    if not isinstance(run_payload, dict):
        raise CheckpointError("Checkpoint run payload must be an object.")
    try:
        checkpoint_run = import_run_payload(run_payload)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise CheckpointError("Checkpoint contains an invalid evaluation-run payload.") from exc

    _validate_manifest_identity(checkpoint_run.manifest, requested_manifest)
    suite_cases = {case.id: case for case in suite.cases}
    completed: dict[str, CaseResult] = {}
    for result in checkpoint_run.cases:
        case_id = result.case.id
        current_case = suite_cases.get(case_id)
        if current_case is None:
            raise CheckpointError(
                f"Checkpoint contains unknown case id {case_id!r}."
            )
        if _canonical_json(_case_payload(current_case)) != _canonical_json(
            _case_payload(result.case)
        ):
            raise CheckpointError(
                f"Case definition {case_id!r} changed since checkpoint creation."
            )
        try:
            validate_system_output(current_case, result.output)
            validate_grader_results(result.graders, case_id)
        except (TypeError, ValueError) as exc:
            raise CheckpointError(
                f"Checkpoint result for case {case_id!r} is invalid."
            ) from exc
        completed[case_id] = result
    return checkpoint_run.manifest, completed


def save_run_checkpoint(
    path: str | Path,
    suite: EvaluationSuite,
    manifest: RunMetadata,
    completed_results: dict[str, CaseResult],
) -> None:
    """Atomically persist the completed subset using the versioned run schema."""
    if not completed_results:
        raise CheckpointError("A checkpoint needs at least one completed case.")
    case_ids = {case.id for case in suite.cases}
    if not set(completed_results).issubset(case_ids):
        raise CheckpointError("Completed checkpoint results contain case ids outside the suite.")

    ordered_results = tuple(
        completed_results[case.id] for case in suite.cases if case.id in completed_results
    )
    try:
        run_payload = export_run_payload(
            EvaluationRun(manifest=manifest, cases=ordered_results)
        )
        payload = {
            "checkpoint_version": _CHECKPOINT_VERSION,
            "suite_fingerprint": _suite_fingerprint(suite),
            "run": run_payload,
        }
        encoded = json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError, RuntimeError) as exc:
        raise CheckpointError("Completed results could not be encoded as a checkpoint.") from exc

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
    except OSError as exc:
        raise CheckpointError(f"Could not atomically write run checkpoint at {target}.") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _validate_manifest_identity(
    checkpoint_manifest: RunMetadata,
    requested_manifest: RunMetadata,
) -> None:
    fields = (
        "suite_version",
        "system_name",
        "system_version",
        "configuration",
        "seed",
        "environment",
    )
    for field_name in fields:
        checkpoint_value = getattr(checkpoint_manifest, field_name)
        requested_value = getattr(requested_manifest, field_name)
        if _canonical_json(checkpoint_value) != _canonical_json(requested_value):
            raise CheckpointError(
                f"Checkpoint {field_name} does not match the requested run manifest."
            )


def _suite_fingerprint(suite: EvaluationSuite) -> str:
    payload = {
        "version": suite.version,
        "cases": [_case_payload(case) for case in suite.cases],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _case_payload(case: EvaluationCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "input": case.input,
        "expected": case.expected,
        "metadata": case.metadata,
        "tags": case.tags,
        "risk_category": case.risk_category,
    }


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CheckpointError("Checkpoint identity contains non-JSON-compatible data.") from exc
