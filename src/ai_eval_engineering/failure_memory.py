"""Persistent, auditable memory of failed evaluation cases.

Stored records include test inputs and expected values, but deliberately do not
persist the system's observed output by default. Callers should still review
test data for sensitive content before writing it to disk.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hashlib
import json
import math
import tempfile
from .domain import EvaluationCase, EvaluationRun, EvaluationSuite


_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FailureRecord:
    """A stable regression-memory entry for one failed grader on one case."""

    failure_id: str
    case: EvaluationCase
    grader: str
    latest_score: float
    latest_details: str
    first_seen_run_id: str
    last_seen_run_id: str
    seen_run_ids: tuple[str, ...]
    suite_version: str
    system_name: str
    system_version: str

    def __post_init__(self) -> None:
        for name, value in (
            ("failure_id", self.failure_id),
            ("grader", self.grader),
            ("latest_details", self.latest_details),
            ("first_seen_run_id", self.first_seen_run_id),
            ("last_seen_run_id", self.last_seen_run_id),
            ("suite_version", self.suite_version),
            ("system_name", self.system_name),
            ("system_version", self.system_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty.")
        if (
            isinstance(self.latest_score, bool)
            or not isinstance(self.latest_score, (int, float))
        ):
            raise TypeError("latest_score must be numeric.")
        try:
            score = float(self.latest_score)
        except OverflowError as exc:
            raise ValueError("latest_score must be finite.") from exc
        if not math.isfinite(score):
            raise ValueError("latest_score must be finite.")
        if not self.seen_run_ids:
            raise ValueError("seen_run_ids must contain at least one run id.")
        if any(not isinstance(run_id, str) or not run_id.strip() for run_id in self.seen_run_ids):
            raise ValueError("seen_run_ids must contain non-empty strings.")
        if len(set(self.seen_run_ids)) != len(self.seen_run_ids):
            raise ValueError("seen_run_ids must be unique.")
        if self.first_seen_run_id != self.seen_run_ids[0]:
            raise ValueError("first_seen_run_id must match the first seen run.")
        if self.last_seen_run_id != self.seen_run_ids[-1]:
            raise ValueError("last_seen_run_id must match the last seen run.")
        try:
            _case_payload(self.case)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"case definition must be JSON-serializable: {exc}") from exc
        expected_failure_id = _build_failure_id(
            self.suite_version, self.system_name, self.case, self.grader
        )
        if self.failure_id != expected_failure_id:
            raise ValueError("failure_id does not match the record's stable identity.")


def extract_failure_records(run: EvaluationRun) -> tuple[FailureRecord, ...]:
    """Extract failed grader/case pairs from a validated evaluation run.

    Failure identity is stable across system versions when the suite version,
    test definition, and grader name are unchanged. Run IDs and observed outputs
    are not included in that identity.
    """
    manifest = run.manifest
    for name, value in (
        ("run_id", manifest.run_id),
        ("suite_version", manifest.suite_version),
        ("system_name", manifest.system_name),
        ("system_version", manifest.system_version),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"run manifest {name} must not be empty.")
    if not run.cases:
        raise ValueError("Cannot extract regression memory from a run with no cases.")

    case_ids: set[str] = set()
    records: list[FailureRecord] = []
    for result in run.cases:
        case = result.case
        if not isinstance(case.id, str) or not case.id.strip():
            raise ValueError("Evaluation run contains an empty or invalid case id.")
        if case.id in case_ids:
            raise ValueError(f"Evaluation run contains duplicate case id {case.id!r}.")
        case_ids.add(case.id)
        if result.output.case_id != case.id:
            raise ValueError(
                f"Output case id {result.output.case_id!r} does not match case id {case.id!r}."
            )
        case_payload = _case_payload(case)
        _canonical_json(case_payload, context=f"case {case.id!r}")

        grader_names: set[str] = set()
        for grader in result.graders:
            if not isinstance(grader.grader, str) or not grader.grader.strip():
                raise ValueError(f"Case {case.id!r} contains an empty grader name.")
            if grader.grader in grader_names:
                raise ValueError(
                    f"Case {case.id!r} contains duplicate grader {grader.grader!r}."
                )
            grader_names.add(grader.grader)
            if not isinstance(grader.passed, bool):
                raise TypeError(
                    f"Case {case.id!r} grader {grader.grader!r} has a non-boolean passed value."
                )
            if (
                isinstance(grader.score, bool)
                or not isinstance(grader.score, (int, float))
            ):
                raise TypeError(
                    f"Case {case.id!r} grader {grader.grader!r} score must be numeric."
                )
            try:
                score = float(grader.score)
            except OverflowError as exc:
                raise ValueError(
                    f"Case {case.id!r} grader {grader.grader!r} score must be finite."
                ) from exc
            if not math.isfinite(score):
                raise ValueError(
                    f"Case {case.id!r} grader {grader.grader!r} score must be finite."
                )
            if not isinstance(grader.details, str):
                raise TypeError(
                    f"Case {case.id!r} grader {grader.grader!r} details must be a string."
                )
            if grader.passed:
                continue

            failure_id = _build_failure_id(
                manifest.suite_version, manifest.system_name, case, grader.grader
            )
            records.append(
                FailureRecord(
                    failure_id=failure_id,
                    case=case,
                    grader=grader.grader,
                    latest_score=score,
                    latest_details=grader.details,
                    first_seen_run_id=manifest.run_id,
                    last_seen_run_id=manifest.run_id,
                    seen_run_ids=(manifest.run_id,),
                    suite_version=manifest.suite_version,
                    system_name=manifest.system_name,
                    system_version=manifest.system_version,
                )
            )
    return tuple(records)


def merge_failure_memory(
    existing: Sequence[FailureRecord],
    observed: Sequence[FailureRecord],
) -> tuple[FailureRecord, ...]:
    """Merge newly observed failures, retaining occurrence history by stable ID.

    Callers should merge runs in chronological order. Existing entry order is
    retained, and newly encountered failures are appended in observed order.
    """
    merged: dict[str, FailureRecord] = {}
    for record in (*existing, *observed):
        if not isinstance(record, FailureRecord):
            raise TypeError("Failure memory items must be FailureRecord instances.")
        previous = merged.get(record.failure_id)
        if previous is None:
            merged[record.failure_id] = record
            continue
        if _case_signature(previous.case) != _case_signature(record.case):
            raise ValueError(
                f"Failure id collision for {record.failure_id!r} with different case definitions."
            )
        seen_run_ids = tuple(dict.fromkeys(previous.seen_run_ids + record.seen_run_ids))
        merged[record.failure_id] = FailureRecord(
            failure_id=record.failure_id,
            case=record.case,
            grader=record.grader,
            latest_score=record.latest_score,
            latest_details=record.latest_details,
            first_seen_run_id=seen_run_ids[0],
            last_seen_run_id=seen_run_ids[-1],
            seen_run_ids=seen_run_ids,
            suite_version=record.suite_version,
            system_name=record.system_name,
            system_version=record.system_version,
        )
    return tuple(merged.values())


def write_failure_memory(
    records: Sequence[FailureRecord],
    path: str | Path,
) -> Path:
    """Write versioned JSONL records atomically without persisting model outputs."""
    materialized = tuple(records)
    if any(not isinstance(record, FailureRecord) for record in materialized):
        raise TypeError("Failure memory items must be FailureRecord instances.")
    failure_ids = [record.failure_id for record in materialized]
    if len(failure_ids) != len(set(failure_ids)):
        raise ValueError("Failure memory must not contain duplicate failure ids.")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            _record_payload(record),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        for record in materialized
    ]
    text = "\n".join(lines) + ("\n" if lines else "")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(text)
            temporary_path = Path(temporary.name)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination


def read_failure_memory(path: str | Path) -> tuple[FailureRecord, ...]:
    """Read and validate versioned JSONL regression-memory records."""
    source = Path(path)
    records: list[FailureRecord] = []
    seen_ids: set[str] = set()
    with source.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
                record = _record_from_payload(payload)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Invalid failure-memory record at {source}:{line_number}: {exc}"
                ) from exc
            if record.failure_id in seen_ids:
                raise ValueError(
                    f"Duplicate failure id {record.failure_id!r} at {source}:{line_number}."
                )
            seen_ids.add(record.failure_id)
            records.append(record)
    return tuple(records)


def build_failure_regression_suite(
    records: Sequence[FailureRecord],
    *,
    version: str,
) -> EvaluationSuite:
    """Build a runnable suite from unique original cases in regression memory."""
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version must not be empty.")
    if not records:
        raise ValueError("At least one failure record is required.")
    by_case_id: dict[str, EvaluationCase] = {}
    for record in records:
        if not isinstance(record, FailureRecord):
            raise TypeError("Failure memory items must be FailureRecord instances.")
        previous = by_case_id.get(record.case.id)
        if previous is not None and _case_signature(previous) != _case_signature(record.case):
            raise ValueError(
                f"Different case definitions share regression case id {record.case.id!r}."
            )
        by_case_id.setdefault(record.case.id, record.case)
    cases = tuple(by_case_id[case_id] for case_id in sorted(by_case_id))
    return EvaluationSuite(version=version, cases=cases)


def _case_payload(case: EvaluationCase) -> dict[str, Any]:
    if not isinstance(case.id, str):
        raise TypeError("case id must be a string.")
    if not case.id.strip():
        raise ValueError("case id must not be empty.")
    if not isinstance(case.input, dict):
        raise TypeError("case input must be a JSON object.")
    if not isinstance(case.metadata, dict):
        raise TypeError("case metadata must be a JSON object.")
    if not isinstance(case.tags, (tuple, list)):
        raise TypeError("case tags must be a sequence of strings.")
    if any(not isinstance(tag, str) for tag in case.tags):
        raise TypeError("case tags must contain only strings.")
    if case.risk_category is not None and not isinstance(case.risk_category, str):
        raise TypeError("case risk_category must be a string or null.")
    return {
        "id": case.id,
        "input": case.input,
        "expected": case.expected,
        "metadata": case.metadata,
        "tags": list(case.tags),
        "risk_category": case.risk_category,
    }


def _build_failure_id(
    suite_version: str,
    system_name: str,
    case: EvaluationCase,
    grader: str,
) -> str:
    identity = {
        "suite_version": suite_version,
        "system_name": system_name,
        "case": _case_payload(case),
        "grader": grader,
    }
    return hashlib.sha256(
        _canonical_json(identity, context="failure identity").encode("utf-8")
    ).hexdigest()[:24]


def _case_signature(case: EvaluationCase) -> str:
    return _canonical_json(_case_payload(case), context=f"case {case.id!r}")


def _canonical_json(value: Any, *, context: str) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} is not valid JSON data: {exc}") from exc


def _record_payload(record: FailureRecord) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "failure_id": record.failure_id,
        "case": _case_payload(record.case),
        "grader": record.grader,
        "latest_score": float(record.latest_score),
        "latest_details": record.latest_details,
        "first_seen_run_id": record.first_seen_run_id,
        "last_seen_run_id": record.last_seen_run_id,
        "seen_run_ids": list(record.seen_run_ids),
        "suite_version": record.suite_version,
        "system_name": record.system_name,
        "system_version": record.system_version,
    }


def _record_from_payload(payload: Any) -> FailureRecord:
    if not isinstance(payload, dict):
        raise TypeError("record must be a JSON object.")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {payload.get('schema_version')!r}.")
    case_data = payload.get("case")
    if not isinstance(case_data, dict):
        raise TypeError("case must be a JSON object.")
    input_data = case_data.get("input")
    metadata = case_data.get("metadata", {})
    tags = case_data.get("tags", [])
    if not isinstance(input_data, dict):
        raise TypeError("case.input must be a JSON object.")
    if not isinstance(metadata, dict):
        raise TypeError("case.metadata must be a JSON object.")
    if not isinstance(tags, list):
        raise TypeError("case.tags must be a list of strings.")
    if any(not isinstance(tag, str) for tag in tags):
        raise TypeError("case.tags must contain only strings.")
    case_id = case_data.get("id")
    if not isinstance(case_id, str):
        raise TypeError("case.id must be a string.")
    if not case_id.strip():
        raise ValueError("case.id must not be empty.")
    risk_category = case_data.get("risk_category")
    if risk_category is not None and not isinstance(risk_category, str):
        raise TypeError("case.risk_category must be a string or null.")
    seen = payload.get("seen_run_ids")
    if not isinstance(seen, list):
        raise TypeError("seen_run_ids must be a list of strings.")
    if any(not isinstance(item, str) for item in seen):
        raise TypeError("seen_run_ids must contain only strings.")
    return FailureRecord(
        failure_id=payload["failure_id"],
        case=EvaluationCase(
            id=case_id,
            input=input_data,
            expected=case_data.get("expected"),
            metadata=metadata,
            tags=tuple(tags),
            risk_category=risk_category,
        ),
        grader=payload["grader"],
        latest_score=payload["latest_score"],
        latest_details=payload["latest_details"],
        first_seen_run_id=payload["first_seen_run_id"],
        last_seen_run_id=payload["last_seen_run_id"],
        seen_run_ids=tuple(seen),
        suite_version=payload["suite_version"],
        system_name=payload["system_name"],
        system_version=payload["system_version"],
    )
