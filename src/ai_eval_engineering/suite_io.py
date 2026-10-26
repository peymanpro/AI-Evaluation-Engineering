"""Versioned JSON interchange for reusable evaluation suites."""

from __future__ import annotations

import json
import os
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

from .contracts import validate_suite
from .domain import EvaluationCase, EvaluationSuite

EVALUATION_SUITE_SCHEMA_VERSION = 1
_ALLOWED_ROOT_FIELDS = {"schema_version", "suite"}
_ALLOWED_SUITE_FIELDS = {"version", "cases"}
_ALLOWED_CASE_FIELDS = {
    "id",
    "input",
    "expected",
    "metadata",
    "tags",
    "risk_category",
}


def get_evaluation_suite_schema() -> dict[str, Any]:
    """Load the packaged JSON Schema for versioned evaluation-suite files."""
    resource = (
        files("ai_eval_engineering")
        .joinpath("schemas")
        .joinpath("evaluation-suite-v1.schema.json")
    )
    try:
        schema = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "The packaged evaluation-suite JSON Schema is unavailable or invalid."
        ) from exc
    if not isinstance(schema, dict):
        raise TypeError("The packaged evaluation-suite JSON Schema must be a JSON object.")
    return schema


def export_suite_payload(suite: EvaluationSuite) -> dict[str, Any]:
    """Serialize a validated suite into the versioned JSON interchange envelope."""
    validate_suite(suite)
    return {
        "schema_version": EVALUATION_SUITE_SCHEMA_VERSION,
        "suite": {
            "version": suite.version,
            "cases": [
                {
                    "id": case.id,
                    "input": case.input,
                    "expected": case.expected,
                    "metadata": case.metadata,
                    "tags": list(case.tags),
                    "risk_category": case.risk_category,
                }
                for case in suite.cases
            ],
        },
    }


def import_suite_payload(payload: Any) -> EvaluationSuite:
    """Validate a suite interchange payload and convert it to typed cases."""
    root = _require_object(payload, "payload")
    version = root.get("schema_version")
    if isinstance(version, bool) or version != EVALUATION_SUITE_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported or missing schema_version; expected "
            f"{EVALUATION_SUITE_SCHEMA_VERSION}."
        )
    _reject_unknown_fields(root, _ALLOWED_ROOT_FIELDS, "payload")
    suite_data = _require_object(root.get("suite"), "suite")
    _reject_unknown_fields(suite_data, _ALLOWED_SUITE_FIELDS, "suite")
    suite_version = _require_string(suite_data.get("version"), "suite.version")
    rows = suite_data.get("cases")
    if not isinstance(rows, list):
        raise TypeError("suite.cases must be a JSON array.")

    cases: list[EvaluationCase] = []
    for index, row in enumerate(rows):
        location = f"suite.cases[{index}]"
        data = _require_object(row, location)
        _reject_unknown_fields(data, _ALLOWED_CASE_FIELDS, location)
        case_id = _require_string(data.get("id"), f"{location}.id")
        if "input" not in data:
            raise ValueError(f"{location}.input is required.")
        input_data = data["input"]
        metadata = data.get("metadata", {})
        tags_data = data.get("tags", [])
        if not isinstance(tags_data, list):
            raise TypeError(f"{location}.tags must be a JSON array of strings.")
        risk_category = data.get("risk_category")
        if risk_category is not None and not isinstance(risk_category, str):
            raise TypeError(f"{location}.risk_category must be a string or null.")
        cases.append(
            EvaluationCase(
                id=case_id,
                input=input_data,
                expected=data.get("expected"),
                metadata=metadata,
                tags=tuple(tags_data),
                risk_category=risk_category,
            )
        )

    suite = EvaluationSuite(version=suite_version, cases=tuple(cases))
    validate_suite(suite)
    return suite


def load_suite_json(path: str | Path) -> EvaluationSuite:
    """Read and validate a versioned evaluation-suite JSON file."""
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {source} at line {exc.lineno}, column {exc.colno}."
        ) from exc
    return import_suite_payload(payload)


def write_suite_json(suite: EvaluationSuite, path: str | Path) -> Path:
    """Write a suite interchange file atomically."""
    payload = export_suite_payload(suite)
    encoded = json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
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
            temporary.write(encoded)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{location} must be a JSON object.")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{location} keys must be strings.")
    return value


def _require_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{location} must be a string.")
    if not value.strip():
        raise ValueError(f"{location} must not be empty.")
    return value


def _reject_unknown_fields(
    data: dict[str, Any],
    allowed: set[str],
    location: str,
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{location} contains unsupported fields: {', '.join(unknown)}.")
