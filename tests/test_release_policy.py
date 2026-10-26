from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

import ai_eval_engineering as public_api
from ai_eval_engineering.release_gate import ReleaseMetricPolicy
from ai_eval_engineering.release_policy import (
    RELEASE_POLICY_SCHEMA_VERSION,
    ReleasePolicy,
    ReleasePolicyError,
    export_release_policy_payload,
    get_release_policy_schema,
    import_release_policy_payload,
    load_release_policy_json,
    validate_release_policy,
    write_release_policy_json,
)


def make_policy() -> ReleasePolicy:
    return ReleasePolicy(
        name="production-release",
        metrics=(
            ReleaseMetricPolicy(
                "quality",
                direction="higher_is_better",
                max_allowed_regression=0.02,
                min_cases=30,
            ),
            ReleaseMetricPolicy(
                "latency_ms",
                direction="lower_is_better",
                max_allowed_regression=10.0,
                min_cases=50,
            ),
            ReleaseMetricPolicy(
                "safety",
                direction="higher_is_better",
                max_allowed_regression=0.0,
                min_cases=40,
            ),
        ),
        confidence=0.95,
        resamples=2500,
        seed=17,
    )


def test_policy_payload_round_trip_preserves_all_metric_and_statistical_settings() -> None:
    policy = make_policy()
    payload = export_release_policy_payload(policy)

    restored = import_release_policy_payload(payload)

    assert restored == policy
    assert payload["schema_version"] == RELEASE_POLICY_SCHEMA_VERSION
    assert [metric["metric"] for metric in payload["policy"]["metrics"]] == [
        "quality",
        "latency_ms",
        "safety",
    ]
    assert payload["policy"]["confidence"] == 0.95
    assert payload["policy"]["resamples"] == 2500
    assert payload["policy"]["seed"] == 17


def test_policy_json_file_round_trip_creates_nested_parent_atomically(tmp_path: Path) -> None:
    policy = make_policy()
    path = tmp_path / "policies" / "release-policy.json"

    assert write_release_policy_json(policy, path) == path
    assert load_release_policy_json(path) == policy
    assert json.loads(path.read_text(encoding="utf-8")) == export_release_policy_payload(policy)


def test_schema_is_packaged_and_matches_repository_copy() -> None:
    schema = get_release_policy_schema()
    repository_schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "release-policy-v1.schema.json")
        .read_text(encoding="utf-8")
    )

    assert schema == repository_schema
    assert schema["properties"]["schema_version"]["const"] == RELEASE_POLICY_SCHEMA_VERSION
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["policy"]["additionalProperties"] is False
    assert schema["$defs"]["metric"]["additionalProperties"] is False
    assert schema["$defs"]["policy"]["properties"]["metrics"]["minItems"] == 1


def test_public_package_exports_policy_io_and_schema_functions() -> None:
    assert public_api.ReleasePolicy is ReleasePolicy
    assert public_api.ReleasePolicyError is ReleasePolicyError
    assert public_api.export_release_policy_payload is export_release_policy_payload
    assert public_api.import_release_policy_payload is import_release_policy_payload
    assert public_api.load_release_policy_json is load_release_policy_json
    assert public_api.write_release_policy_json is write_release_policy_json
    assert public_api.get_release_policy_schema is get_release_policy_schema
    assert public_api.RELEASE_POLICY_SCHEMA_VERSION == RELEASE_POLICY_SCHEMA_VERSION


@pytest.mark.parametrize("version", [0, 2, True, None])
def test_unknown_or_boolean_schema_version_is_rejected(version: Any) -> None:
    payload = export_release_policy_payload(make_policy())
    payload["schema_version"] = version

    with pytest.raises(ReleasePolicyError, match="schema_version"):
        import_release_policy_payload(payload)


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("root", "unexpected"),
        ("policy", "unexpected"),
        ("metric", "unexpected"),
    ],
)
def test_unknown_contract_fields_are_rejected(location: str, field: str) -> None:
    payload = export_release_policy_payload(make_policy())
    if location == "root":
        payload[field] = "ignored fields can hide typos"
    elif location == "policy":
        payload["policy"][field] = "not supported"
    else:
        payload["policy"]["metrics"][0][field] = "not supported"

    with pytest.raises(ReleasePolicyError, match="unsupported fields"):
        import_release_policy_payload(payload)


def test_empty_metric_list_is_rejected() -> None:
    payload = export_release_policy_payload(make_policy())
    payload["policy"]["metrics"] = []

    with pytest.raises(ReleasePolicyError, match="at least one metric"):
        import_release_policy_payload(payload)


def test_duplicate_metric_names_are_rejected() -> None:
    payload = export_release_policy_payload(make_policy())
    payload["policy"]["metrics"][1]["metric"] = "quality"

    with pytest.raises(ValueError, match="duplicate metric"):
        import_release_policy_payload(payload)


@pytest.mark.parametrize("confidence", [True, 0, 1, -0.1, 1.1, math.inf, math.nan])
def test_invalid_confidence_is_rejected(confidence: Any) -> None:
    payload = export_release_policy_payload(make_policy())
    payload["policy"]["confidence"] = confidence

    with pytest.raises((TypeError, ValueError), match="confidence"):
        import_release_policy_payload(payload)


@pytest.mark.parametrize("resamples", [True, 99, 1.5, 0])
def test_invalid_resample_count_is_rejected(resamples: Any) -> None:
    payload = export_release_policy_payload(make_policy())
    payload["policy"]["resamples"] = resamples

    with pytest.raises((TypeError, ValueError), match="resamples"):
        import_release_policy_payload(payload)


@pytest.mark.parametrize("seed", [True, 1.5, "17"])
def test_invalid_seed_is_rejected(seed: Any) -> None:
    payload = export_release_policy_payload(make_policy())
    payload["policy"]["seed"] = seed

    with pytest.raises(TypeError, match="seed"):
        import_release_policy_payload(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("direction", "neutral", "direction"),
        ("direction", True, "direction"),
        ("max_allowed_regression", -0.01, "non-negative"),
        ("max_allowed_regression", math.inf, "finite"),
        ("min_cases", True, "integer"),
        ("min_cases", 1, "at least 2"),
    ],
)
def test_invalid_metric_policy_is_rejected(
    field: str, value: Any, message: str
) -> None:
    payload = export_release_policy_payload(make_policy())
    payload["policy"]["metrics"][0][field] = value

    with pytest.raises((TypeError, ValueError), match=message):
        import_release_policy_payload(payload)


def test_missing_required_policy_field_is_rejected() -> None:
    payload = export_release_policy_payload(make_policy())
    del payload["policy"]["seed"]

    with pytest.raises(ReleasePolicyError, match="missing required fields: seed"):
        import_release_policy_payload(payload)


def test_malformed_policy_json_reports_line_and_column(tmp_path: Path) -> None:
    path = tmp_path / "broken-policy.json"
    path.write_text('{"schema_version":', encoding="utf-8")

    with pytest.raises(ReleasePolicyError, match=r"line 1, column"):
        load_release_policy_json(path)


def test_validate_release_policy_rejects_non_policy_objects() -> None:
    with pytest.raises(TypeError, match="ReleasePolicy"):
        validate_release_policy(object())  # type: ignore[arg-type]
