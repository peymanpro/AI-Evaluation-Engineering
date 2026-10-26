"""Versioned multi-metric release policies for recorded-run comparisons."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from .release_gate import ReleaseMetricPolicy

RELEASE_POLICY_SCHEMA_VERSION = 1
_ROOT_FIELDS = {"schema_version", "policy"}
_POLICY_FIELDS = {"name", "confidence", "resamples", "seed", "metrics"}
_METRIC_FIELDS = {
    "metric",
    "direction",
    "max_allowed_regression",
    "min_cases",
}


class ReleasePolicyError(ValueError):
    """A release-policy-v1 file is malformed or contains unsupported settings."""


@dataclass(frozen=True)
class ReleasePolicy:
    """Reproducible configuration for a multi-metric release gate."""

    name: str
    metrics: tuple[ReleaseMetricPolicy, ...]
    confidence: float = 0.95
    resamples: int = 2000
    seed: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("policy.name must not be empty.")
        if not isinstance(self.metrics, tuple) or not self.metrics:
            raise ValueError("policy.metrics must be a non-empty tuple.")
        if any(not isinstance(item, ReleaseMetricPolicy) for item in self.metrics):
            raise TypeError("policy.metrics must contain ReleaseMetricPolicy instances.")
        names = [item.metric for item in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("policy.metrics must not contain duplicate metric names.")

        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise TypeError("policy.confidence must be numeric.")
        try:
            confidence_value = float(self.confidence)
        except OverflowError as exc:
            raise ValueError("policy.confidence must be finite and between 0 and 1.") from exc
        if not math.isfinite(confidence_value) or not 0.0 < confidence_value < 1.0:
            raise ValueError("policy.confidence must be finite and between 0 and 1.")

        if isinstance(self.resamples, bool) or not isinstance(self.resamples, int):
            raise TypeError("policy.resamples must be an integer.")
        if self.resamples < 100:
            raise ValueError("policy.resamples must be at least 100.")

        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("policy.seed must be an integer.")

        object.__setattr__(self, "confidence", confidence_value)


def get_release_policy_schema() -> dict[str, Any]:
    """Load the packaged release-policy-v1 JSON Schema."""
    resource = (
        files("ai_eval_engineering")
        .joinpath("schemas")
        .joinpath("release-policy-v1.schema.json")
    )
    try:
        schema = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "The packaged release-policy JSON Schema is unavailable or invalid."
        ) from exc
    if not isinstance(schema, dict):
        raise TypeError("The packaged release-policy JSON Schema must be a JSON object.")
    if schema.get("properties", {}).get("schema_version", {}).get("const") != (
        RELEASE_POLICY_SCHEMA_VERSION
    ):
        raise RuntimeError("The packaged release-policy JSON Schema has an unsupported version.")
    return schema


def export_release_policy_payload(policy: ReleasePolicy) -> dict[str, Any]:
    """Serialize a release policy to its versioned interchange envelope."""
    validate_release_policy(policy)
    return {
        "schema_version": RELEASE_POLICY_SCHEMA_VERSION,
        "policy": {
            "name": policy.name,
            "confidence": policy.confidence,
            "resamples": policy.resamples,
            "seed": policy.seed,
            "metrics": [
                {
                    "metric": item.metric,
                    "direction": item.direction,
                    "max_allowed_regression": item.max_allowed_regression,
                    "min_cases": item.min_cases,
                }
                for item in policy.metrics
            ],
        },
    }


def import_release_policy_payload(payload: Any) -> ReleasePolicy:
    """Validate and parse a release-policy-v1 payload."""
    root = _require_object(payload, "payload")
    _reject_unknown_fields(root, _ROOT_FIELDS, "payload")
    version = root.get("schema_version")
    if isinstance(version, bool) or version != RELEASE_POLICY_SCHEMA_VERSION:
        raise ReleasePolicyError(
            f"Unsupported or missing schema_version; expected {RELEASE_POLICY_SCHEMA_VERSION}."
        )
    if "policy" not in root:
        raise ReleasePolicyError("payload.policy is required.")

    policy_data = _require_object(root["policy"], "policy")
    _reject_unknown_fields(policy_data, _POLICY_FIELDS, "policy")
    required = _POLICY_FIELDS
    missing = sorted(required - set(policy_data))
    if missing:
        raise ReleasePolicyError(f"policy is missing required fields: {', '.join(missing)}.")

    rows = _require_list(policy_data["metrics"], "policy.metrics")
    if not rows:
        raise ReleasePolicyError("policy.metrics must contain at least one metric.")
    metrics: list[ReleaseMetricPolicy] = []
    for index, row in enumerate(rows):
        location = f"policy.metrics[{index}]"
        data = _require_object(row, location)
        _reject_unknown_fields(data, _METRIC_FIELDS, location)
        missing_metric_fields = sorted(_METRIC_FIELDS - set(data))
        if missing_metric_fields:
            raise ReleasePolicyError(
                f"{location} is missing required fields: "
                f"{', '.join(missing_metric_fields)}."
            )

        metric = _require_non_empty_string(data["metric"], f"{location}.metric")
        direction = data["direction"]
        if direction not in {"higher_is_better", "lower_is_better"}:
            raise ReleasePolicyError(
                f"{location}.direction must be 'higher_is_better' or 'lower_is_better'."
            )
        tolerance = _require_number(
            data["max_allowed_regression"],
            f"{location}.max_allowed_regression",
        )
        minimum = data["min_cases"]
        if isinstance(minimum, bool) or not isinstance(minimum, int):
            raise TypeError(f"{location}.min_cases must be an integer.")
        metrics.append(
            ReleaseMetricPolicy(
                metric=metric,
                direction=direction,
                max_allowed_regression=tolerance,
                min_cases=minimum,
            )
        )

    return ReleasePolicy(
        name=_require_non_empty_string(policy_data["name"], "policy.name"),
        metrics=tuple(metrics),
        confidence=_require_number(policy_data["confidence"], "policy.confidence"),
        resamples=_require_integer(policy_data["resamples"], "policy.resamples"),
        seed=_require_integer(policy_data["seed"], "policy.seed"),
    )


def load_release_policy_json(path: str | Path) -> ReleasePolicy:
    """Read and validate a versioned release policy from UTF-8 JSON."""
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ReleasePolicyError(
            f"Invalid release policy JSON in {source} at line {exc.lineno}, column {exc.colno}."
        ) from exc
    return import_release_policy_payload(payload)


def write_release_policy_json(policy: ReleasePolicy, path: str | Path) -> Path:
    """Atomically write a validated release-policy-v1 file."""
    payload = export_release_policy_payload(policy)
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


def validate_release_policy(policy: ReleasePolicy) -> None:
    """Validate a policy instance before serialization or execution."""
    if not isinstance(policy, ReleasePolicy):
        raise TypeError("policy must be a ReleasePolicy.")
    # Re-run constructor validation to protect against unsafe deserialization or
    # instances manufactured without the dataclass initializer.
    ReleasePolicy(
        name=policy.name,
        metrics=policy.metrics,
        confidence=policy.confidence,
        resamples=policy.resamples,
        seed=policy.seed,
    )


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


def _require_number(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{location} must be numeric.")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise ValueError(f"{location} must be finite.") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{location} must be finite.")
    return numeric


def _require_integer(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{location} must be an integer.")
    return int(value)


def _reject_unknown_fields(
    data: dict[str, Any],
    allowed: set[str],
    location: str,
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ReleasePolicyError(
            f"{location} contains unsupported fields: {', '.join(unknown)}."
        )
