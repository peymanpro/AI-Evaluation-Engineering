from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from ai_eval_engineering import (
    EVALUATION_SUITE_SCHEMA_VERSION,
    EvaluationCase,
    EvaluationSuite,
    export_suite_payload,
    get_evaluation_suite_schema,
    import_suite_payload,
    load_suite_json,
    write_suite_json,
)


def example_suite() -> EvaluationSuite:
    return EvaluationSuite(
        version="support-suite-v1",
        cases=(
            EvaluationCase(
                id="order-status",
                input={"question": "Where is my order?", "locale": "en"},
                expected={"intent": "order_status"},
                metadata={"source": "smoke-fixture"},
                tags=("support", "stable"),
                risk_category="data_leakage",
            ),
            EvaluationCase(
                id="refund-policy",
                input={"question": "What is your refund policy?"},
                expected={"intent": "refund_policy"},
                tags=("support",),
            ),
        ),
    )


def test_suite_payload_round_trip_preserves_case_contracts() -> None:
    suite = example_suite()

    payload = export_suite_payload(suite)
    restored = import_suite_payload(payload)

    assert payload["schema_version"] == EVALUATION_SUITE_SCHEMA_VERSION
    assert restored == suite


def test_suite_file_round_trip_is_valid_json_and_creates_parent_directory(
    tmp_path: Path,
) -> None:
    suite = example_suite()
    target = tmp_path / "nested" / "suites" / "support.json"

    assert write_suite_json(suite, target) == target
    loaded = load_suite_json(target)

    assert loaded == suite
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["suite"]["version"] == "support-suite-v1"


def test_suite_schema_is_available_as_a_packaged_resource() -> None:
    schema = get_evaluation_suite_schema()

    assert schema["$schema"].endswith("/2020-12/schema")
    assert schema["properties"]["schema_version"]["const"] == 1
    assert schema["properties"]["suite"]["$ref"] == "#/$defs/suite"


@pytest.mark.parametrize("version", [True, 0, 2, "1", None])
def test_suite_import_rejects_unsupported_schema_versions(version: Any) -> None:
    payload = export_suite_payload(example_suite())
    payload["schema_version"] = version

    with pytest.raises(ValueError, match="schema_version"):
        import_suite_payload(payload)


def test_suite_import_rejects_unknown_fields_at_every_level() -> None:
    payload = export_suite_payload(example_suite())
    payload["unexpected"] = "not allowed"

    with pytest.raises(ValueError, match="unsupported fields"):
        import_suite_payload(payload)

    payload = export_suite_payload(example_suite())
    payload["suite"]["unexpected"] = "not allowed"

    with pytest.raises(ValueError, match="unsupported fields"):
        import_suite_payload(payload)

    payload = export_suite_payload(example_suite())
    payload["suite"]["cases"][0]["unexpected"] = "not allowed"

    with pytest.raises(ValueError, match="unsupported fields"):
        import_suite_payload(payload)


def test_suite_import_rejects_duplicate_case_ids() -> None:
    payload = export_suite_payload(example_suite())
    payload["suite"]["cases"].append(payload["suite"]["cases"][0])

    with pytest.raises(ValueError, match="Duplicate case id"):
        import_suite_payload(payload)


def test_suite_import_rejects_non_finite_numbers() -> None:
    payload = export_suite_payload(example_suite())
    payload["suite"]["cases"][0]["input"]["temperature"] = math.nan

    with pytest.raises(ValueError, match="non-finite"):
        import_suite_payload(payload)


def test_suite_import_requires_object_inputs_and_string_tags() -> None:
    payload = export_suite_payload(example_suite())
    payload["suite"]["cases"][0]["input"] = "not-an-object"

    with pytest.raises(TypeError, match="input must be an object"):
        import_suite_payload(payload)

    payload = export_suite_payload(example_suite())
    payload["suite"]["cases"][0]["tags"] = ["valid", 12]

    with pytest.raises(TypeError, match=r"tags\[1\]"):
        import_suite_payload(payload)


def test_empty_suite_can_be_serialized_and_loaded(tmp_path: Path) -> None:
    empty = EvaluationSuite(version="empty-suite-v1", cases=())
    path = tmp_path / "empty.json"

    write_suite_json(empty, path)

    assert load_suite_json(path) == empty
