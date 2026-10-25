"""Versioned JSON interchange for evaluation runs produced by external tools."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

from .domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    GraderResult,
    JsonObject,
    RunMetadata,
    SystemOutput,
)

EXTERNAL_RUN_SCHEMA_VERSION = 1


def import_run_payload(payload: Any) -> EvaluationRun:
    """Validate a versioned interchange payload and convert it to domain objects.

    This is a provider-neutral file-format boundary, not a provider-specific
    SDK integration. Numeric values and nested JSON data are validated before
    they enter the evaluation pipeline.
    """
    root = _require_object(payload, "payload")
    version = root.get("schema_version")
    if isinstance(version, bool) or version != EXTERNAL_RUN_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported or missing schema_version; expected "
            f"{EXTERNAL_RUN_SCHEMA_VERSION}."
        )

    manifest_data = _require_object(root.get("manifest"), "manifest")
    manifest = _parse_manifest(manifest_data)

    case_rows = _require_list(root.get("cases"), "cases")
    if not case_rows:
        raise ValueError("cases must contain at least one case result.")

    results: list[CaseResult] = []
    seen_case_ids: set[str] = set()
    for index, row in enumerate(case_rows):
        location = f"cases[{index}]"
        result_data = _require_object(row, location)
        case_data = _require_object(result_data.get("case"), f"{location}.case")
        case = _parse_case(case_data, f"{location}.case")
        if case.id in seen_case_ids:
            raise ValueError(f"Duplicate case id {case.id!r} in cases.")
        seen_case_ids.add(case.id)

        output_data = _require_object(
            result_data.get("output"), f"{location}.output"
        )
        output = _parse_output(output_data, case.id, f"{location}.output")

        grader_rows = _require_list(
            result_data.get("graders"), f"{location}.graders"
        )
        if not grader_rows:
            raise ValueError(f"{location}.graders must not be empty.")
        graders: list[GraderResult] = []
        seen_graders: set[str] = set()
        for grader_index, grader_row in enumerate(grader_rows):
            grader_location = f"{location}.graders[{grader_index}]"
            grader_data = _require_object(grader_row, grader_location)
            grader = _parse_grader(grader_data, grader_location)
            if grader.grader in seen_graders:
                raise ValueError(
                    f"Duplicate grader {grader.grader!r} for case {case.id!r}."
                )
            seen_graders.add(grader.grader)
            graders.append(grader)

        results.append(CaseResult(case, output, tuple(graders)))

    return EvaluationRun(manifest=manifest, cases=tuple(results))


def export_run_payload(run: EvaluationRun) -> dict[str, Any]:
    """Serialize a domain run into the versioned external interchange format."""
    if not isinstance(run, EvaluationRun):
        raise TypeError("run must be an EvaluationRun.")
    payload = {
        "schema_version": EXTERNAL_RUN_SCHEMA_VERSION,
        "manifest": _to_json_value(run.manifest),
        "cases": [_to_json_value(result) for result in run.cases],
    }
    # Round-trip validation keeps the exporter from emitting a payload that
    # the corresponding importer itself would reject.
    import_run_payload(payload)
    return payload


def load_run_json(path: str | Path) -> EvaluationRun:
    """Read and validate one versioned JSON interchange file."""
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {source} at line {exc.lineno}, column {exc.colno}."
        ) from exc
    return import_run_payload(payload)


def write_run_json(run: EvaluationRun, path: str | Path) -> Path:
    """Write a validated interchange file atomically."""
    payload = export_run_payload(run)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"

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


def _parse_manifest(data: dict[str, Any]) -> RunMetadata:
    run_id = _require_string(data.get("run_id"), "manifest.run_id")
    suite_version = _require_string(
        data.get("suite_version"), "manifest.suite_version"
    )
    system_name = _require_string(data.get("system_name"), "manifest.system_name")
    system_version = _require_string(
        data.get("system_version"), "manifest.system_version"
    )
    timestamp_utc = _require_string(
        data.get("timestamp_utc"), "manifest.timestamp_utc"
    )
    configuration = _require_json_object(
        data.get("configuration", {}), "manifest.configuration"
    )
    environment = _require_json_object(
        data.get("environment", {}), "manifest.environment"
    )

    seed = data.get("seed")
    if seed is not None and (
        isinstance(seed, bool) or not isinstance(seed, int)
    ):
        raise TypeError("manifest.seed must be an integer or null.")

    return RunMetadata(
        run_id=run_id,
        suite_version=suite_version,
        system_name=system_name,
        system_version=system_version,
        configuration=configuration,
        seed=seed,
        timestamp_utc=timestamp_utc,
        environment=environment,
    )


def _parse_case(data: dict[str, Any], location: str) -> EvaluationCase:
    case_id = _require_string(data.get("id"), f"{location}.id")
    input_data = _require_json_object(data.get("input"), f"{location}.input")
    metadata = _require_json_object(
        data.get("metadata", {}), f"{location}.metadata"
    )
    tags_data = data.get("tags", [])
    if not isinstance(tags_data, list):
        raise TypeError(f"{location}.tags must be a list of strings.")
    tags = tuple(
        _require_string(tag, f"{location}.tags[{index}]")
        for index, tag in enumerate(tags_data)
    )

    risk_category = data.get("risk_category")
    if risk_category is not None and not isinstance(risk_category, str):
        raise TypeError(f"{location}.risk_category must be a string or null.")

    expected = data.get("expected")
    _validate_json_value(expected, f"{location}.expected")
    return EvaluationCase(
        id=case_id,
        input=input_data,
        expected=expected,
        metadata=metadata,
        tags=tags,
        risk_category=risk_category,
    )


def _parse_output(
    data: dict[str, Any],
    expected_case_id: str,
    location: str,
) -> SystemOutput:
    case_id = _require_string(data.get("case_id"), f"{location}.case_id")
    if case_id != expected_case_id:
        raise ValueError(
            f"{location}.case_id {case_id!r} does not match case id "
            f"{expected_case_id!r}."
        )
    if "output" not in data:
        raise ValueError(f"{location}.output field is required.")
    output = data["output"]
    _validate_json_value(output, f"{location}.output")

    latency_ms = _optional_nonnegative_number(data.get("latency_ms"), f"{location}.latency_ms")
    cost_usd = _optional_nonnegative_number(data.get("cost_usd"), f"{location}.cost_usd")

    trace_data = data.get("trace", [])
    if not isinstance(trace_data, list):
        raise TypeError(f"{location}.trace must be a list of JSON objects.")
    trace = tuple(
        _require_json_object(item, f"{location}.trace[{index}]")
        for index, item in enumerate(trace_data)
    )
    return SystemOutput(
        case_id=case_id,
        output=output,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        trace=list(trace),
    )


def _parse_grader(data: dict[str, Any], location: str) -> GraderResult:
    name = _require_string(data.get("grader"), f"{location}.grader")
    passed = data.get("passed")
    if not isinstance(passed, bool):
        raise TypeError(f"{location}.passed must be a boolean.")

    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise TypeError(f"{location}.score must be numeric.")
    try:
        numeric_score = float(score)
    except OverflowError as exc:
        raise ValueError(f"{location}.score must be finite.") from exc
    if not math.isfinite(numeric_score):
        raise ValueError(f"{location}.score must be finite.")

    details = data.get("details")
    if not isinstance(details, str):
        raise TypeError(f"{location}.details must be a string.")
    metadata = _require_json_object(
        data.get("metadata", {}), f"{location}.metadata"
    )
    return GraderResult(
        grader=name,
        passed=passed,
        score=numeric_score,
        details=details,
        metadata=metadata,
    )


def _optional_nonnegative_number(value: Any, location: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{location} must be numeric or null.")
    try:
        numeric_value = float(value)
    except OverflowError as exc:
        raise ValueError(f"{location} must be finite and non-negative.") from exc
    if not math.isfinite(numeric_value) or numeric_value < 0:
        raise ValueError(f"{location} must be finite and non-negative.")
    return numeric_value


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{location} must be a JSON object.")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{location} keys must be strings.")
    return value


def _require_json_object(value: Any, location: str) -> JsonObject:
    result = _require_object(value, location)
    _validate_json_value(result, location)
    return result


def _require_list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{location} must be a JSON array.")
    return value


def _require_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{location} must be a string.")
    if not value.strip():
        raise ValueError(f"{location} must not be empty.")
    return value


def _validate_json_value(value: Any, location: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} contains a non-finite number.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{location} object keys must be strings.")
            _validate_json_value(item, f"{location}.{key}")
        return
    raise TypeError(f"{location} contains a non-JSON value of type {type(value).__name__}.")


def _to_json_value(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _to_json_value(item)
            for key, item in vars(value).items()
        }
    if isinstance(value, tuple):
        return [_to_json_value(item) for item in value]
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_json_value(item) for key, item in value.items()}
    return value
