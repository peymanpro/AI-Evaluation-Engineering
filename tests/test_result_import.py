from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

import ai_eval_engineering as public_api
from ai_eval_engineering.domain import EvaluationRun
from ai_eval_engineering.result_import import (
    EXTERNAL_RUN_SCHEMA_VERSION,
    export_run_payload,
    import_run_payload,
    load_run_json,
    write_run_json,
)


def payload() -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_RUN_SCHEMA_VERSION,
        "manifest": {
            "run_id": "external-run-1",
            "suite_version": "suite-v3",
            "system_name": "external-assistant",
            "system_version": "build-42",
            "configuration": {"temperature": 0.0, "provider": "example"},
            "seed": 7,
            "timestamp_utc": "2026-10-25T23:00:00Z",
            "environment": {"runtime": "test"},
        },
        "cases": [
            {
                "case": {
                    "id": "case-1",
                    "input": {"prompt": "What is 2 + 2?"},
                    "expected": {"answer": 4},
                    "metadata": {"source": "fixture"},
                    "tags": ["math", "smoke"],
                    "risk_category": None,
                },
                "output": {
                    "case_id": "case-1",
                    "output": {"answer": 4},
                    "latency_ms": 12.5,
                    "cost_usd": 0.0002,
                    "trace": [{"step": 1, "tool": "calculator"}],
                },
                "graders": [
                    {
                        "grader": "exact_match",
                        "passed": True,
                        "score": 1.0,
                        "details": "answer matched",
                        "metadata": {"rubric_version": "r1"},
                    }
                ],
            }
        ],
    }


def test_packaged_json_schema_matches_repository_contract() -> None:
    schema = public_api.get_external_run_schema()
    repository_schema_path = (
        Path(__file__).parents[1] / "schemas" / "external-run-v1.schema.json"
    )
    repository_schema = json.loads(repository_schema_path.read_text(encoding="utf-8"))

    assert schema == repository_schema
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == EXTERNAL_RUN_SCHEMA_VERSION
    assert schema["additionalProperties"] is False
    for name in ("manifest", "case", "output", "grader", "caseResult"):
        assert schema["$defs"][name]["additionalProperties"] is False
    assert schema["$defs"]["jsonObject"]["additionalProperties"]["$ref"] == "#/$defs/jsonValue"


def test_import_and_export_round_trip_preserves_domain_data() -> None:
    original = payload()

    run = import_run_payload(original)
    exported = export_run_payload(run)

    assert isinstance(run, EvaluationRun)
    assert run.manifest.run_id == "external-run-1"
    assert run.manifest.configuration["temperature"] == 0.0
    assert run.cases[0].case.tags == ("math", "smoke")
    assert run.cases[0].output.latency_ms == 12.5
    assert run.cases[0].graders[0].passed
    assert exported == original


@pytest.mark.parametrize(
    "location",
    ["root", "manifest", "case_result", "case", "output", "grader"],
)
def test_unknown_fields_are_rejected_at_contract_boundaries(location: str) -> None:
    data = payload()
    if location == "root":
        data["future_field"] = "must-not-be-dropped"
    elif location == "manifest":
        data["manifest"]["future_field"] = "must-not-be-dropped"
    elif location == "case_result":
        data["cases"][0]["future_field"] = "must-not-be-dropped"
    elif location == "case":
        data["cases"][0]["case"]["future_field"] = "must-not-be-dropped"
    elif location == "output":
        data["cases"][0]["output"]["future_field"] = "must-not-be-dropped"
    else:
        data["cases"][0]["graders"][0]["future_field"] = "must-not-be-dropped"

    with pytest.raises(ValueError, match="unsupported fields: future_field"):
        import_run_payload(data)


def test_free_form_json_objects_remain_extensible_and_round_trip() -> None:
    data = payload()
    data["manifest"]["configuration"]["provider_extension"] = "kept"
    data["manifest"]["environment"]["runtime_extension"] = {"enabled": True}
    data["cases"][0]["case"]["input"]["client_extension"] = {"nested": [1, 2]}
    data["cases"][0]["case"]["metadata"]["annotation"] = "kept"
    data["cases"][0]["output"]["output"]["trace_extension"] = "kept"
    data["cases"][0]["output"]["trace"][0]["vendor_event_id"] = "evt-1"
    data["cases"][0]["graders"][0]["metadata"]["grader_extension"] = "kept"

    run = import_run_payload(data)

    assert export_run_payload(run) == data


@pytest.mark.parametrize("cycle_kind", ["dict", "list"])
def test_circular_python_values_are_rejected_as_invalid_json(cycle_kind: str) -> None:
    data = payload()
    if cycle_kind == "dict":
        cycle: dict[str, Any] | list[Any] = {}
        cycle["self"] = cycle
    else:
        cycle = []
        cycle.append(cycle)

    data["manifest"]["configuration"]["cycle"] = cycle

    with pytest.raises(ValueError, match="circular reference"):
        import_run_payload(data)


def test_json_file_round_trip_and_nested_destination(tmp_path: Path) -> None:
    run = import_run_payload(payload())
    path = tmp_path / "nested" / "external-run.json"

    assert write_run_json(run, path) == path
    assert load_run_json(path) == run
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["schema_version"] == EXTERNAL_RUN_SCHEMA_VERSION


def test_unknown_schema_version_is_rejected() -> None:
    data = payload()
    data["schema_version"] = 99

    with pytest.raises(ValueError, match="schema_version"):
        import_run_payload(data)


def test_empty_runs_are_rejected_as_non_evidence() -> None:
    data = payload()
    data["cases"] = []

    with pytest.raises(ValueError, match="at least one case"):
        import_run_payload(data)


def test_duplicate_case_ids_are_rejected() -> None:
    data = payload()
    data["cases"].append(copy.deepcopy(data["cases"][0]))

    with pytest.raises(ValueError, match="Duplicate case id"):
        import_run_payload(data)


def test_output_case_id_must_match_case_id() -> None:
    data = payload()
    data["cases"][0]["output"]["case_id"] = "another-case"

    with pytest.raises(ValueError, match="does not match"):
        import_run_payload(data)


def test_duplicate_grader_names_are_rejected() -> None:
    data = payload()
    data["cases"][0]["graders"].append(copy.deepcopy(data["cases"][0]["graders"][0]))

    with pytest.raises(ValueError, match="Duplicate grader"):
        import_run_payload(data)


@pytest.mark.parametrize("passed", [1, "true", None])
def test_grader_passed_must_be_boolean(passed: Any) -> None:
    data = payload()
    data["cases"][0]["graders"][0]["passed"] = passed

    with pytest.raises(TypeError, match="passed must be a boolean"):
        import_run_payload(data)


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf])
def test_non_finite_grader_scores_are_rejected(score: float) -> None:
    data = payload()
    data["cases"][0]["graders"][0]["score"] = score

    with pytest.raises(ValueError, match="finite"):
        import_run_payload(data)


@pytest.mark.parametrize("cost", [-1.0, math.inf, math.nan])
def test_invalid_costs_are_rejected(cost: float) -> None:
    data = payload()
    data["cases"][0]["output"]["cost_usd"] = cost

    with pytest.raises(ValueError, match="finite and non-negative"):
        import_run_payload(data)


def test_non_json_nested_metadata_is_rejected() -> None:
    data = payload()
    data["manifest"]["configuration"]["unexpected"] = object()

    with pytest.raises(TypeError, match="non-JSON"):
        import_run_payload(data)


def test_invalid_json_file_reports_location(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"schema_version":', encoding="utf-8")

    with pytest.raises(ValueError, match=r"line 1, column"):
        load_run_json(path)


def test_missing_output_value_is_not_treated_as_null_output() -> None:
    data = payload()
    del data["cases"][0]["output"]["output"]

    with pytest.raises(ValueError, match="output field is required"):
        import_run_payload(data)



def test_json_schema_documents_the_same_supported_version() -> None:
    schema_path = Path(__file__).parents[1] / "schemas" / "external-run-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["properties"]["schema_version"]["const"] == EXTERNAL_RUN_SCHEMA_VERSION
    assert "manifest" in schema["required"]
    assert "cases" in schema["required"]


def test_interchange_functions_are_available_from_public_package() -> None:
    assert public_api.import_run_payload is import_run_payload
    assert public_api.export_run_payload is export_run_payload
    assert public_api.load_run_json is load_run_json
    assert public_api.write_run_json is write_run_json
    assert public_api.EXTERNAL_RUN_SCHEMA_VERSION == EXTERNAL_RUN_SCHEMA_VERSION
