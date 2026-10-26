"""Auditable per-case execution outcomes for failure-aware evaluation runs."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from .contracts import (
    validate_grader_results,
    validate_run_inputs,
    validate_system_output,
)
from .domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from .suite_io import EVALUATION_SUITE_SCHEMA_VERSION, import_suite_payload

EXECUTION_REPORT_SCHEMA_VERSION = 1

ExecutionStatus = Literal[
    "completed",
    "adapter_error",
    "output_validation_error",
    "grader_error",
    "grader_contract_error",
]
FailureStage = Literal[
    "adapter",
    "output_validation",
    "grader_execution",
    "grader_contract",
]

_STATUS_TO_STAGE: dict[str, FailureStage] = {
    "adapter_error": "adapter",
    "output_validation_error": "output_validation",
    "grader_error": "grader_execution",
    "grader_contract_error": "grader_contract",
}
_ALLOWED_STATUSES = {"completed", *_STATUS_TO_STAGE}
_ALLOWED_FAILURE_STAGES = set(_STATUS_TO_STAGE.values())
_ROOT_FIELDS = {"schema_version", "manifest", "cases"}
_MANIFEST_FIELDS = {
    "run_id",
    "suite_version",
    "system_name",
    "system_version",
    "timestamp_utc",
    "configuration",
    "environment",
    "seed",
}
_CASE_RESULT_FIELDS = {"case", "status", "output", "graders", "failure"}
_CASE_FIELDS = {"id", "input", "expected", "metadata", "tags", "risk_category"}
_OUTPUT_FIELDS = {"case_id", "output", "latency_ms", "cost_usd", "trace"}
_GRADER_FIELDS = {"grader", "passed", "score", "details", "metadata"}
_FAILURE_FIELDS = {"stage", "exception_type", "message"}


class ExecutionReportError(ValueError):
    """An execution report is invalid or cannot be represented as the v1 format."""


@dataclass(frozen=True)
class CaseExecutionFailure:
    """A captured exception from one evaluation case.

    Exception messages may contain provider details or user data. Treat reports
    as potentially sensitive artifacts when storing or sharing them.
    """

    stage: FailureStage
    exception_type: str
    message: str


@dataclass(frozen=True)
class CaseExecutionResult:
    """The execution outcome for one case, separate from semantic grader pass/fail."""

    case: EvaluationCase
    status: ExecutionStatus
    output: SystemOutput | None = None
    graders: tuple[GraderResult, ...] = ()
    failure: CaseExecutionFailure | None = None

    @property
    def completed(self) -> bool:
        """Whether system execution and all configured graders completed validly."""
        return self.status == "completed"


@dataclass(frozen=True)
class EvaluationExecutionReport:
    """Ordered outcomes for every case attempted by a failure-aware runner."""

    manifest: RunMetadata
    cases: tuple[CaseExecutionResult, ...]

    @property
    def is_complete(self) -> bool:
        """True only if every case completed system execution and grading."""
        return all(item.completed for item in self.cases)

    @property
    def completed_count(self) -> int:
        return sum(item.completed for item in self.cases)

    @property
    def failed_count(self) -> int:
        return len(self.cases) - self.completed_count

    def to_evaluation_run(self) -> EvaluationRun:
        """Convert only a fully completed report to the release-gate run contract.

        Partial reports are intentionally not coerced into ordinary runs, since
        that could make missing evidence look like a valid baseline or candidate.
        A grader result with passed=False is still a completed evaluation.
        """
        validate_execution_report(self)
        if not self.is_complete:
            raise ExecutionReportError(
                "Execution report contains failed cases; it cannot be converted "
                "to a complete EvaluationRun."
            )
        case_results: list[CaseResult] = []
        for item in self.cases:
            assert item.output is not None
            case_results.append(CaseResult(item.case, item.output, item.graders))
        return EvaluationRun(self.manifest, tuple(case_results))


def failure_result(
    case: EvaluationCase,
    status: Literal[
        "adapter_error",
        "output_validation_error",
        "grader_error",
        "grader_contract_error",
    ],
    error: Exception,
    *,
    output: SystemOutput | None = None,
    graders: tuple[GraderResult, ...] = (),
) -> CaseExecutionResult:
    """Build a typed failed-case record without converting failure into a score."""
    stage = _STATUS_TO_STAGE[status]
    return CaseExecutionResult(
        case=case,
        status=status,
        output=output,
        graders=graders,
        failure=CaseExecutionFailure(
            stage=stage,
            exception_type=f"{type(error).__module__}.{type(error).__qualname__}",
            message=str(error),
        ),
    )


def validate_execution_report(report: EvaluationExecutionReport) -> None:
    """Validate the report before it is persisted or converted to an EvaluationRun."""
    if not isinstance(report, EvaluationExecutionReport):
        raise TypeError("report must be an EvaluationExecutionReport.")
    if not isinstance(report.manifest, RunMetadata):
        raise TypeError("report.manifest must be RunMetadata.")
    if not isinstance(report.cases, tuple):
        raise TypeError("report.cases must be a tuple.")
    for index, item in enumerate(report.cases):
        if not isinstance(item, CaseExecutionResult):
            raise TypeError(f"cases[{index}] must be a CaseExecutionResult.")
    suite = EvaluationSuite(
        version=report.manifest.suite_version,
        cases=tuple(item.case for item in report.cases),
    )
    validate_run_inputs(suite, report.manifest)

    seen_case_ids: set[str] = set()
    for index, item in enumerate(report.cases):
        location = f"cases[{index}]"
        if not isinstance(item, CaseExecutionResult):
            raise TypeError(f"{location} must be a CaseExecutionResult.")
        case_id = item.case.id
        if case_id in seen_case_ids:
            raise ValueError(f"Duplicate case id {case_id!r} in execution report.")
        seen_case_ids.add(case_id)
        if item.status not in _ALLOWED_STATUSES:
            raise ValueError(f"{location}.status is not a supported execution status.")

        if item.status == "completed":
            if item.output is None:
                raise ValueError(f"{location}.output is required for a completed case.")
            if item.failure is not None:
                raise ValueError(f"{location}.failure must be null for a completed case.")
            if not item.graders:
                raise ValueError(f"{location}.graders must not be empty for a completed case.")
            validate_system_output(item.case, item.output)
            validate_grader_results(item.graders, case_id)
            continue

        expected_stage = _STATUS_TO_STAGE[item.status]
        if not isinstance(item.failure, CaseExecutionFailure):
            raise TypeError(f"{location}.failure is required for a failed case.")
        if item.failure.stage != expected_stage:
            raise ValueError(
                f"{location}.failure.stage must be {expected_stage!r} for status {item.status!r}."
            )
        if not isinstance(item.failure.exception_type, str) or not item.failure.exception_type.strip():
            raise ValueError(f"{location}.failure.exception_type must not be empty.")
        if not isinstance(item.failure.message, str):
            raise TypeError(f"{location}.failure.message must be a string.")

        if item.status in {"adapter_error", "output_validation_error"}:
            if item.output is not None:
                raise ValueError(f"{location}.output must be null for status {item.status!r}.")
            if item.graders:
                raise ValueError(f"{location}.graders must be empty for status {item.status!r}.")
        else:
            if item.output is None:
                raise ValueError(f"{location}.output is required for status {item.status!r}.")
            validate_system_output(item.case, item.output)
            validate_grader_results(item.graders, case_id)


def get_execution_report_schema() -> dict[str, Any]:
    """Load the packaged JSON Schema for execution-report-v1."""
    resource = (
        files("ai_eval_engineering")
        .joinpath("schemas")
        .joinpath("execution-report-v1.schema.json")
    )
    try:
        schema = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "The packaged execution-report JSON Schema is unavailable or invalid."
        ) from exc
    if not isinstance(schema, dict):
        raise TypeError("The packaged execution-report JSON Schema must be a JSON object.")
    if schema.get("properties", {}).get("schema_version", {}).get("const") != (
        EXECUTION_REPORT_SCHEMA_VERSION
    ):
        raise RuntimeError("The packaged execution-report JSON Schema has an unsupported version.")
    return schema


def export_execution_report(report: EvaluationExecutionReport) -> dict[str, Any]:
    """Serialize a report to the versioned, provider-neutral execution format."""
    validate_execution_report(report)
    return {
        "schema_version": EXECUTION_REPORT_SCHEMA_VERSION,
        "manifest": _manifest_payload(report.manifest),
        "cases": [
            {
                "case": _case_payload(item.case),
                "status": item.status,
                "output": _output_payload(item.output) if item.output is not None else None,
                "graders": [_grader_payload(grader) for grader in item.graders],
                "failure": _failure_payload(item.failure) if item.failure is not None else None,
            }
            for item in report.cases
        ],
    }


def import_execution_report_payload(payload: Any) -> EvaluationExecutionReport:
    """Validate a versioned execution report and reconstruct typed outcomes."""
    root = _require_object(payload, "payload")
    if set(root) - _ROOT_FIELDS:
        _reject_unknown_fields(root, _ROOT_FIELDS, "payload")
    version = root.get("schema_version")
    if isinstance(version, bool) or version != EXECUTION_REPORT_SCHEMA_VERSION:
        raise ExecutionReportError(
            f"Unsupported or missing schema_version; expected {EXECUTION_REPORT_SCHEMA_VERSION}."
        )
    if "manifest" not in root or "cases" not in root:
        raise ExecutionReportError("payload must include manifest and cases.")

    manifest_data = _require_object(root["manifest"], "manifest")
    _reject_unknown_fields(manifest_data, _MANIFEST_FIELDS, "manifest")
    manifest = _parse_manifest(manifest_data)
    rows = _require_list(root["cases"], "cases")
    cases: list[CaseExecutionResult] = []

    for index, row in enumerate(rows):
        location = f"cases[{index}]"
        result_data = _require_object(row, location)
        _reject_unknown_fields(result_data, _CASE_RESULT_FIELDS, location)
        if set(result_data) != _CASE_RESULT_FIELDS:
            missing = sorted(_CASE_RESULT_FIELDS - set(result_data))
            raise ExecutionReportError(
                f"{location} is missing required fields: {', '.join(missing)}."
            )

        case_data = _require_object(result_data["case"], f"{location}.case")
        _reject_unknown_fields(case_data, _CASE_FIELDS, f"{location}.case")
        suite_payload = {
            "schema_version": EVALUATION_SUITE_SCHEMA_VERSION,
            "suite": {
                "version": manifest.suite_version,
                "cases": [case_data],
            },
        }
        case = import_suite_payload(suite_payload).cases[0]

        status = result_data["status"]
        if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
            raise ExecutionReportError(f"{location}.status is not a supported execution status.")

        output_data = result_data["output"]
        output: SystemOutput | None
        if output_data is None:
            output = None
        else:
            output_object = _require_object(output_data, f"{location}.output")
            _reject_unknown_fields(output_object, _OUTPUT_FIELDS, f"{location}.output")
            output = _parse_output(output_object, case, f"{location}.output")

        grader_rows = _require_list(result_data["graders"], f"{location}.graders")
        graders = tuple(
            _parse_grader(_require_object(grader, f"{location}.graders[{grader_index}]"),
                          f"{location}.graders[{grader_index}]")
            for grader_index, grader in enumerate(grader_rows)
        )

        failure_data = result_data["failure"]
        failure: CaseExecutionFailure | None
        if failure_data is None:
            failure = None
        else:
            failure_object = _require_object(failure_data, f"{location}.failure")
            _reject_unknown_fields(failure_object, _FAILURE_FIELDS, f"{location}.failure")
            if set(failure_object) != _FAILURE_FIELDS:
                missing = sorted(_FAILURE_FIELDS - set(failure_object))
                raise ExecutionReportError(
                    f"{location}.failure is missing required fields: {', '.join(missing)}."
                )
            stage = failure_object["stage"]
            exception_type = failure_object["exception_type"]
            message = failure_object["message"]
            if not isinstance(stage, str) or stage not in _ALLOWED_FAILURE_STAGES:
                raise ExecutionReportError(f"{location}.failure.stage is unsupported.")
            failure = CaseExecutionFailure(
                stage=stage,  # type: ignore[arg-type]
                exception_type=_require_non_empty_string(
                    exception_type, f"{location}.failure.exception_type"
                ),
                message=_require_string(message, f"{location}.failure.message"),
            )

        cases.append(
            CaseExecutionResult(
                case=case,
                status=status,  # type: ignore[arg-type]
                output=output,
                graders=graders,
                failure=failure,
            )
        )

    report = EvaluationExecutionReport(manifest=manifest, cases=tuple(cases))
    validate_execution_report(report)
    return report


def write_execution_report(
    report: EvaluationExecutionReport,
    path: str | Path,
) -> Path:
    """Atomically write a validated execution report as UTF-8 JSON."""
    payload = export_execution_report(report)
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


def load_execution_report(path: str | Path) -> EvaluationExecutionReport:
    """Read and validate one execution-report-v1 JSON file."""
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ExecutionReportError(
            f"Invalid execution report JSON in {source} at line {exc.lineno}, column {exc.colno}."
        ) from exc
    return import_execution_report_payload(payload)


def _parse_manifest(data: dict[str, Any]) -> RunMetadata:
    required = {
        "run_id", "suite_version", "system_name", "system_version", "timestamp_utc"
    }
    missing = sorted(required - set(data))
    if missing:
        raise ExecutionReportError(f"manifest is missing required fields: {', '.join(missing)}.")
    seed = data.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise TypeError("manifest.seed must be an integer or null.")
    configuration = _require_object(data.get("configuration", {}), "manifest.configuration")
    environment = _require_object(data.get("environment", {}), "manifest.environment")
    return RunMetadata(
        run_id=_require_non_empty_string(data["run_id"], "manifest.run_id"),
        suite_version=_require_non_empty_string(data["suite_version"], "manifest.suite_version"),
        system_name=_require_non_empty_string(data["system_name"], "manifest.system_name"),
        system_version=_require_non_empty_string(data["system_version"], "manifest.system_version"),
        configuration=configuration,
        seed=seed,
        timestamp_utc=_require_non_empty_string(data["timestamp_utc"], "manifest.timestamp_utc"),
        environment=environment,
    )


def _parse_output(data: dict[str, Any], case: EvaluationCase, location: str) -> SystemOutput:
    if "case_id" not in data or "output" not in data:
        raise ExecutionReportError(f"{location} must include case_id and output.")
    trace = data.get("trace", [])
    if not isinstance(trace, list) or any(not isinstance(item, dict) for item in trace):
        raise TypeError(f"{location}.trace must be a list of JSON objects.")
    output = SystemOutput(
        case_id=_require_non_empty_string(data["case_id"], f"{location}.case_id"),
        output=data["output"],
        latency_ms=_optional_nonnegative_number(data.get("latency_ms"), f"{location}.latency_ms"),
        cost_usd=_optional_nonnegative_number(data.get("cost_usd"), f"{location}.cost_usd"),
        trace=trace,
    )
    validate_system_output(case, output)
    return output


def _parse_grader(data: dict[str, Any], location: str) -> GraderResult:
    _reject_unknown_fields(data, _GRADER_FIELDS, location)
    required = {"grader", "passed", "score", "details"}
    missing = sorted(required - set(data))
    if missing:
        raise ExecutionReportError(f"{location} is missing required fields: {', '.join(missing)}.")
    passed = data["passed"]
    if not isinstance(passed, bool):
        raise TypeError(f"{location}.passed must be a boolean.")
    score = data["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise TypeError(f"{location}.score must be numeric.")
    try:
        numeric_score = float(score)
    except OverflowError as exc:
        raise ValueError(f"{location}.score must be finite.") from exc
    if not math.isfinite(numeric_score):
        raise ValueError(f"{location}.score must be finite.")
    details = data["details"]
    if not isinstance(details, str):
        raise TypeError(f"{location}.details must be a string.")
    metadata = _require_object(data.get("metadata", {}), f"{location}.metadata")
    return GraderResult(
        grader=_require_non_empty_string(data["grader"], f"{location}.grader"),
        passed=passed,
        score=numeric_score,
        details=details,
        metadata=metadata,
    )


def _manifest_payload(manifest: RunMetadata) -> dict[str, Any]:
    return {
        "run_id": manifest.run_id,
        "suite_version": manifest.suite_version,
        "system_name": manifest.system_name,
        "system_version": manifest.system_version,
        "configuration": manifest.configuration,
        "seed": manifest.seed,
        "timestamp_utc": manifest.timestamp_utc,
        "environment": manifest.environment,
    }


def _case_payload(case: EvaluationCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "input": case.input,
        "expected": case.expected,
        "metadata": case.metadata,
        "tags": list(case.tags),
        "risk_category": case.risk_category,
    }


def _output_payload(output: SystemOutput) -> dict[str, Any]:
    return {
        "case_id": output.case_id,
        "output": output.output,
        "latency_ms": output.latency_ms,
        "cost_usd": output.cost_usd,
        "trace": output.trace,
    }


def _grader_payload(grader: GraderResult) -> dict[str, Any]:
    return {
        "grader": grader.grader,
        "passed": grader.passed,
        "score": grader.score,
        "details": grader.details,
        "metadata": grader.metadata,
    }


def _failure_payload(failure: CaseExecutionFailure) -> dict[str, str]:
    return {
        "stage": failure.stage,
        "exception_type": failure.exception_type,
        "message": failure.message,
    }


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{location} must be a JSON object.")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{location} keys must be strings.")
    return value


def _require_list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{location} must be a JSON array.")
    return value


def _require_non_empty_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{location} must be a string.")
    if not value.strip():
        raise ValueError(f"{location} must not be empty.")
    return value


def _require_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{location} must be a string.")
    return value


def _optional_nonnegative_number(value: Any, location: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{location} must be numeric or null.")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise ValueError(f"{location} must be finite and non-negative.") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{location} must be finite and non-negative.")
    return numeric


def _reject_unknown_fields(data: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ExecutionReportError(
            f"{location} contains unsupported fields: {', '.join(unknown)}."
        )
