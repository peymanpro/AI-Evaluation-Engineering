from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from ai_eval_engineering.domain import EvaluationRun
from ai_eval_engineering.promptfoo import (
    SUPPORTED_PROMPTFOO_RESULT_VERSION,
    import_promptfoo_payload,
    load_promptfoo_json,
)


FIXTURE = Path(__file__).parent / "fixtures" / "promptfoo-v3.json"


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def import_openai_prompt_zero(payload: dict[str, Any] | None = None) -> EvaluationRun:
    return import_promptfoo_payload(
        payload if payload is not None else load_fixture(),
        system_name="arithmetic-assistant",
        system_version="commit-a1b2c3",
        suite_version="arithmetic-suite-v1",
        provider_id="openai:mock:answerer",
        prompt_idx=0,
    )


def test_imports_selected_prompt_provider_slice_into_domain_run() -> None:
    run = import_openai_prompt_zero()

    assert isinstance(run, EvaluationRun)
    assert run.manifest.run_id == "promptfoo-promptfoo-eval-fixture-001"
    assert run.manifest.suite_version == "arithmetic-suite-v1"
    assert run.manifest.system_name == "arithmetic-assistant"
    assert run.manifest.system_version == "commit-a1b2c3"
    assert run.manifest.timestamp_utc == "2026-10-26T00:30:00Z"
    assert run.manifest.configuration["provider_id"] == "openai:mock:answerer"
    assert run.manifest.configuration["prompt_idx"] == 0
    assert run.manifest.configuration["prompt_ids"] == ["prompt-hash-v1"]

    assert len(run.cases) == 3
    first, second, timed_out = run.cases
    assert first.case.id == "test-000000"
    assert first.case.input == {"vars": {"question": "What is 2 + 2?"}}
    assert first.case.expected == {
        "assertions": [{"type": "equals", "value": {"answer": 4}}],
        "options": {},
    }
    assert first.case.tags == ("arithmetic",)
    assert first.output.output == {"answer": 4}
    assert first.output.latency_ms == 10.0
    assert first.output.cost_usd == 0.001
    assert first.graders[0].grader == "promptfoo"
    assert first.graders[0].passed is True
    assert first.graders[0].score == 1.0
    assert first.graders[0].details == "Expected answer matched"
    assert first.graders[0].metadata["named_scores"] == {"correctness": 1.0}
    assert second.case.id == "test-000001"
    assert second.graders[0].passed is False
    assert second.graders[0].details == "Expected answer 8, received 7"
    assert timed_out.case.id == "test-000002"
    assert timed_out.output.output is None
    assert timed_out.output.latency_ms is None
    assert timed_out.graders[0].passed is False
    assert timed_out.graders[0].details == "Provider timed out"
    assert timed_out.graders[0].metadata["failureReason"] == 2


def test_selector_can_resolve_provider_before_prompt_ambiguity() -> None:
    run = import_promptfoo_payload(
        load_fixture(),
        system_name="single-provider-system",
        system_version="v1",
        suite_version="suite-v1",
        provider_id="anthropic:mock:answerer",
    )

    assert len(run.cases) == 1
    assert run.manifest.configuration["provider_id"] == "anthropic:mock:answerer"
    assert run.manifest.configuration["prompt_idx"] == 0


def test_ambiguous_export_requires_explicit_provider_and_prompt() -> None:
    with pytest.raises(ValueError, match="multiple providers"):
        import_promptfoo_payload(
            load_fixture(),
            system_name="system",
            system_version="v1",
            suite_version="suite-v1",
            prompt_idx=0,
        )
    with pytest.raises(ValueError, match="multiple prompts"):
        import_promptfoo_payload(
            load_fixture(),
            system_name="system",
            system_version="v1",
            suite_version="suite-v1",
            provider_id="openai:mock:answerer",
        )
    with pytest.raises(ValueError, match="specify provider_id"):
        import_promptfoo_payload(
            load_fixture(),
            system_name="system",
            system_version="v1",
            suite_version="suite-v1",
        )


def test_load_promptfoo_json_reads_export_file(tmp_path: Path) -> None:
    destination = tmp_path / "exports" / "promptfoo.json"
    destination.parent.mkdir()
    destination.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    run = load_promptfoo_json(
        destination,
        system_name="system",
        system_version="v1",
        suite_version="suite-v1",
        provider_id="openai:mock:answerer",
        prompt_idx=0,
    )

    assert len(run.cases) == 3
    assert run.manifest.configuration["source"] == "promptfoo"


def test_missing_eval_id_generates_repeatable_run_id() -> None:
    data = load_fixture()
    data["evalId"] = None

    first = import_openai_prompt_zero(data)
    second = import_openai_prompt_zero(data)

    assert first.manifest.run_id == second.manifest.run_id
    assert first.manifest.run_id.startswith("promptfoo-")


def test_unknown_result_version_is_rejected() -> None:
    data = load_fixture()
    data["results"]["version"] = 999

    with pytest.raises(ValueError, match="expected 3"):
        import_openai_prompt_zero(data)


def test_duplicate_test_indices_in_selected_slice_are_rejected() -> None:
    data = load_fixture()
    duplicate = copy.deepcopy(data["results"]["results"][0])
    duplicate["id"] = "duplicate-row"
    data["results"]["results"].append(duplicate)

    with pytest.raises(ValueError, match="Duplicate testIdx"):
        import_openai_prompt_zero(data)


def test_conflicting_vars_in_row_and_test_case_are_rejected() -> None:
    data = load_fixture()
    data["results"]["results"][0]["vars"]["question"] = "different question"

    with pytest.raises(ValueError, match="conflicting vars"):
        import_openai_prompt_zero(data)


def test_response_without_output_is_rejected_unless_error_is_present() -> None:
    data = load_fixture()
    row = data["results"]["results"][0]
    row["response"] = {"cost": 0.1}

    with pytest.raises(ValueError, match="missing its output field"):
        import_openai_prompt_zero(data)


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf, True, "1.0"])
def test_invalid_scores_are_rejected(score: Any) -> None:
    data = load_fixture()
    data["results"]["results"][0]["score"] = score

    with pytest.raises((TypeError, ValueError)):
        import_openai_prompt_zero(data)


@pytest.mark.parametrize("latency", [-1, math.nan, math.inf, "12"])
def test_invalid_latency_is_rejected(latency: Any) -> None:
    data = load_fixture()
    data["results"]["results"][0]["latencyMs"] = latency

    with pytest.raises((TypeError, ValueError)):
        import_openai_prompt_zero(data)


def test_missing_provider_and_prompt_selectors_are_reported() -> None:
    with pytest.raises(ValueError, match="provider_id is not present"):
        import_promptfoo_payload(
            load_fixture(),
            system_name="system",
            system_version="v1",
            suite_version="suite-v1",
            provider_id="missing:provider",
            prompt_idx=0,
        )
    with pytest.raises(ValueError, match="prompt_idx is not present"):
        import_promptfoo_payload(
            load_fixture(),
            system_name="system",
            system_version="v1",
            suite_version="suite-v1",
            provider_id="openai:mock:answerer",
            prompt_idx=22,
        )


def test_selector_contract_rejects_empty_system_identity() -> None:
    with pytest.raises(ValueError, match="system_name"):
        import_promptfoo_payload(
            load_fixture(),
            system_name=" ",
            system_version="v1",
            suite_version="suite-v1",
            provider_id="openai:mock:answerer",
            prompt_idx=0,
        )
    with pytest.raises(TypeError, match="prompt_idx"):
        import_promptfoo_payload(
            load_fixture(),
            system_name="system",
            system_version="v1",
            suite_version="suite-v1",
            provider_id="openai:mock:answerer",
            prompt_idx=True,  # type: ignore[arg-type]
        )


def test_supported_promptfoo_version_constant_matches_current_export() -> None:
    assert load_fixture()["results"]["version"] == SUPPORTED_PROMPTFOO_RESULT_VERSION
