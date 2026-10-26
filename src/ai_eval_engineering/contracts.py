"""Preflight validation for suites, run manifests, and recorded case results."""

from __future__ import annotations

import math
from typing import Any

from .domain import (
    EvaluationCase,
    EvaluationSuite,
    GraderResult,
    RunMetadata,
    SystemOutput,
)


def validate_suite(suite: EvaluationSuite) -> None:
    """Validate suite identity, unique case IDs, and JSON-compatible case data."""
    if not isinstance(suite, EvaluationSuite):
        raise TypeError("suite must be an EvaluationSuite.")
    _require_non_empty_string(suite.version, "suite.version")

    seen_ids: set[str] = set()
    for index, case in enumerate(suite.cases):
        location = f"suite.cases[{index}]"
        if not isinstance(case, EvaluationCase):
            raise TypeError(f"{location} must be an EvaluationCase.")
        _require_non_empty_string(case.id, f"{location}.id")
        if case.id in seen_ids:
            raise ValueError(f"Duplicate case id {case.id!r} in suite.")
        seen_ids.add(case.id)

        if not isinstance(case.input, dict):
            raise TypeError(f"{location}.input must be an object.")
        _assert_json_compatible(case.input, f"{location}.input", set())
        if not isinstance(case.metadata, dict):
            raise TypeError(f"{location}.metadata must be an object.")
        _assert_json_compatible(case.metadata, f"{location}.metadata", set())
        _assert_json_compatible(case.expected, f"{location}.expected", set())

        if not isinstance(case.tags, (tuple, list)):
            raise TypeError(f"{location}.tags must be a sequence of strings.")
        for tag_index, tag in enumerate(case.tags):
            _require_non_empty_string(tag, f"{location}.tags[{tag_index}]")
        if case.risk_category is not None:
            _require_non_empty_string(case.risk_category, f"{location}.risk_category")


def validate_run_inputs(suite: EvaluationSuite, manifest: RunMetadata) -> None:
    """Reject inconsistent suite/manifest pairs before the system is called."""
    validate_suite(suite)
    if not isinstance(manifest, RunMetadata):
        raise TypeError("manifest must be a RunMetadata.")
    for name in ("run_id", "suite_version", "system_name", "system_version", "timestamp_utc"):
        _require_non_empty_string(getattr(manifest, name), f"manifest.{name}")
    if manifest.suite_version != suite.version:
        raise ValueError(
            f"manifest.suite_version {manifest.suite_version!r} does not match "
            f"suite.version {suite.version!r}."
        )
    if manifest.seed is not None and (
        isinstance(manifest.seed, bool) or not isinstance(manifest.seed, int)
    ):
        raise TypeError("manifest.seed must be an integer or None.")
    if not isinstance(manifest.configuration, dict):
        raise TypeError("manifest.configuration must be an object.")
    _assert_json_compatible(manifest.configuration, "manifest.configuration", set())
    if not isinstance(manifest.environment, dict):
        raise TypeError("manifest.environment must be an object.")
    _assert_json_compatible(manifest.environment, "manifest.environment", set())


def validate_system_output(case: EvaluationCase, output: SystemOutput) -> None:
    """Validate an adapter output before any grader consumes it."""
    if not isinstance(output, SystemOutput):
        raise TypeError(f"System adapter must return SystemOutput for case {case.id!r}.")
    if not isinstance(output.case_id, str) or output.case_id != case.id:
        raise ValueError(
            f"System returned case id {output.case_id!r} for expected {case.id!r}."
        )
    _assert_json_compatible(output.output, f"output for case {case.id!r}", set())
    for name in ("latency_ms", "cost_usd"):
        value = getattr(output, name)
        if value is not None:
            _require_finite_number(value, f"output.{name}", non_negative=True)
    if not isinstance(output.trace, list):
        raise TypeError(f"output.trace for case {case.id!r} must be a list.")
    for index, event in enumerate(output.trace):
        if not isinstance(event, dict):
            raise TypeError(f"output.trace[{index}] for case {case.id!r} must be an object.")
        _assert_json_compatible(event, f"output.trace[{index}]", set())


def validate_grader_results(results: tuple[GraderResult, ...], case_id: str) -> None:
    """Reject malformed grader output before it enters reports or statistics."""
    seen_names: set[str] = set()
    for index, result in enumerate(results):
        location = f"graders[{index}] for case {case_id!r}"
        if not isinstance(result, GraderResult):
            raise TypeError(f"{location} must be a GraderResult.")
        _require_non_empty_string(result.grader, f"{location}.grader")
        if result.grader in seen_names:
            raise ValueError(f"Duplicate grader name {result.grader!r} for case {case_id!r}.")
        seen_names.add(result.grader)
        if not isinstance(result.passed, bool):
            raise TypeError(f"{location}.passed must be a boolean.")
        _require_finite_number(result.score, f"{location}.score")
        if not isinstance(result.details, str):
            raise TypeError(f"{location}.details must be a string.")
        if not isinstance(result.metadata, dict):
            raise TypeError(f"{location}.metadata must be an object.")
        _assert_json_compatible(result.metadata, f"{location}.metadata", set())


def _require_non_empty_string(value: Any, location: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{location} must be a string.")
    if not value.strip():
        raise ValueError(f"{location} must not be empty.")


def _require_finite_number(
    value: Any, location: str, *, non_negative: bool = False
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{location} must be numeric.")
    try:
        converted = float(value)
    except OverflowError as exc:
        raise ValueError(f"{location} must be finite.") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{location} must be finite.")
    if non_negative and converted < 0:
        raise ValueError(f"{location} must be non-negative.")


def _assert_json_compatible(value: Any, location: str, ancestors: set[int]) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} contains a non-finite number.")
        return
    if isinstance(value, (list, tuple, dict)):
        identity = id(value)
        if identity in ancestors:
            raise ValueError(f"{location} contains a circular reference.")
        ancestors.add(identity)
        try:
            if isinstance(value, dict):
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise TypeError(f"{location} object keys must be strings.")
                    _assert_json_compatible(item, f"{location}.{key}", ancestors)
            else:
                for index, item in enumerate(value):
                    _assert_json_compatible(item, f"{location}[{index}]", ancestors)
        finally:
            ancestors.remove(identity)
        return
    raise TypeError(f"{location} contains non-JSON-compatible value {type(value).__name__}.")
