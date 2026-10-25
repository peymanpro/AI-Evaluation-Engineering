"""Adapter for Promptfoo v3 JSON evaluation exports."""

from __future__ import annotations

import hashlib
import json
import math
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

SUPPORTED_PROMPTFOO_RESULT_VERSION = 3


def import_promptfoo_payload(
    payload: Any,
    *,
    system_name: str,
    system_version: str,
    suite_version: str,
    provider_id: str | None = None,
    prompt_idx: int | None = None,
    run_id: str | None = None,
) -> EvaluationRun:
    """Convert a Promptfoo v3 JSON export into one comparable EvaluationRun.

    Promptfoo files may contain multiple providers and prompts for every test.
    To prevent accidental mixing of systems, this importer requires the selected
    export to resolve to exactly one provider ID and one prompt index. Supply
    selectors when an export includes multiple combinations.

    The source result's testIdx becomes a stable case ID within the selected
    suite. The caller supplies system and suite versions because Promptfoo's
    prompt/provider identifiers alone do not define the user's release policy.
    """
    _require_nonempty_string(system_name, "system_name")
    _require_nonempty_string(system_version, "system_version")
    _require_nonempty_string(suite_version, "suite_version")
    if provider_id is not None:
        _require_nonempty_string(provider_id, "provider_id")
    if prompt_idx is not None:
        _require_index(prompt_idx, "prompt_idx")

    root = _require_object(payload, "payload")
    result_envelope = _require_object(root.get("results"), "results")
    result_version = result_envelope.get("version")
    if (
        isinstance(result_version, bool)
        or not isinstance(result_version, int)
        or result_version != SUPPORTED_PROMPTFOO_RESULT_VERSION
    ):
        raise ValueError(
            "Unsupported Promptfoo result version; expected "
            f"{SUPPORTED_PROMPTFOO_RESULT_VERSION}."
        )
    timestamp = _require_nonempty_string(
        result_envelope.get("timestamp"), "results.timestamp"
    )
    result_rows = _require_list(result_envelope.get("results"), "results.results")
    if not result_rows:
        raise ValueError("Promptfoo export contains no evaluation results.")

    parsed_rows: list[tuple[dict[str, Any], str, int, int]] = []
    provider_ids: set[str] = set()
    prompt_indices: set[int] = set()
    for row_index, raw_row in enumerate(result_rows):
        location = f"results.results[{row_index}]"
        row = _require_object(raw_row, location)
        test_index = _require_index(row.get("testIdx"), f"{location}.testIdx")
        row_prompt_idx = _require_index(
            row.get("promptIdx"), f"{location}.promptIdx"
        )
        row_provider_id = _provider_id(row.get("provider"), f"{location}.provider")
        parsed_rows.append((row, row_provider_id, row_prompt_idx, test_index))
        provider_ids.add(row_provider_id)
        prompt_indices.add(row_prompt_idx)

    if provider_id is not None and provider_id not in provider_ids:
        raise ValueError(
            "Requested provider_id is not present in the Promptfoo export: "
            + provider_id
        )
    if prompt_idx is not None and prompt_idx not in prompt_indices:
        raise ValueError(
            "Requested prompt_idx is not present in the Promptfoo export: "
            + str(prompt_idx)
        )

    candidates = [
        row_data
        for row_data in parsed_rows
        if (provider_id is None or row_data[1] == provider_id)
        and (prompt_idx is None or row_data[2] == prompt_idx)
    ]
    if not candidates:
        raise ValueError("No results match the supplied provider/prompt selectors.")

    selected_providers = {row_data[1] for row_data in candidates}
    selected_prompts = {row_data[2] for row_data in candidates}
    if len(selected_providers) != 1:
        raise ValueError(
            "Promptfoo export contains multiple providers; specify provider_id."
        )
    if len(selected_prompts) != 1:
        raise ValueError(
            "Promptfoo export contains multiple prompts; specify prompt_idx."
        )

    selected_provider = next(iter(selected_providers))
    selected_prompt = next(iter(selected_prompts))
    selected_rows = [
        row_data
        for row_data in candidates
        if row_data[1] == selected_provider and row_data[2] == selected_prompt
    ]
    if not selected_rows:
        raise ValueError("No results match the selected provider and prompt.")

    test_indices = [row_data[3] for row_data in selected_rows]
    if len(test_indices) != len(set(test_indices)):
        raise ValueError(
            "Duplicate testIdx values exist for the selected provider and prompt."
        )

    cases: list[CaseResult] = []
    prompt_ids: set[str] = set()
    for row, row_provider_id, row_prompt_idx, test_index in sorted(
        selected_rows, key=lambda item: item[3]
    ):
        location = f"testIdx={test_index}, promptIdx={row_prompt_idx}"
        case_data = _require_object(row.get("testCase"), f"{location}.testCase")
        variables = row.get("vars", case_data.get("vars", {}))
        variables_object = _require_json_object(variables, f"{location}.vars")
        case_variables = case_data.get("vars")
        if case_variables is not None:
            declared_variables = _require_json_object(
                case_variables, f"{location}.testCase.vars"
            )
            if declared_variables != variables_object:
                raise ValueError(
                    f"{location} has conflicting vars and testCase.vars values."
                )

        assertions = case_data.get("assert", [])
        if not isinstance(assertions, list):
            raise TypeError(f"{location}.testCase.assert must be an array.")
        _validate_json_value(assertions, f"{location}.testCase.assert")
        options = _require_json_object(
            case_data.get("options", {}), f"{location}.testCase.options"
        )
        test_metadata = _require_json_object(
            case_data.get("metadata", {}), f"{location}.testCase.metadata"
        )
        _validate_json_value(options, f"{location}.testCase.options")

        prompt_id_value = row.get("promptId")
        if prompt_id_value is not None:
            prompt_id = _require_nonempty_string(
                prompt_id_value, f"{location}.promptId"
            )
            prompt_ids.add(prompt_id)

        case_id = f"test-{test_index:06d}"
        case = EvaluationCase(
            id=case_id,
            input={"vars": variables_object},
            expected={"assertions": assertions, "options": options},
            metadata={
                "source": "promptfoo",
                "test_metadata": test_metadata,
                "description": row.get("description"),
            },
            tags=_tags(test_metadata.get("tags"), f"{location}.testCase.metadata.tags"),
        )

        success = row.get("success")
        if not isinstance(success, bool):
            raise TypeError(f"{location}.success must be a boolean.")
        score = _require_finite_number(row.get("score"), f"{location}.score")
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"{location}.score must be between 0 and 1.")

        error = row.get("error")
        if error is not None and not isinstance(error, str):
            raise TypeError(f"{location}.error must be a string or null.")
        response = row.get("response")
        if response is not None:
            response_object = _require_object(response, f"{location}.response")
            output_value = response_object.get("output", row.get("text"))
        elif error:
            # Provider/runtime errors can be valid failed evidence with no output.
            output_value = None
            response_object = {}
        elif "text" in row:
            output_value = row["text"]
            response_object = {}
        else:
            raise ValueError(
                f"{location} has neither a response, text, nor a provider error."
            )
        _validate_json_value(output_value, f"{location}.response.output")

        latency = _optional_nonnegative_number(
            row.get("latencyMs"), f"{location}.latencyMs"
        )
        cost_value = row.get("cost")
        if cost_value is None:
            cost_value = response_object.get("cost")
        cost = _optional_nonnegative_number(cost_value, f"{location}.cost")

        grading_result_value = row.get("gradingResult")
        if grading_result_value is None:
            grading_result: JsonObject = {}
            details = error or (
                "Promptfoo result passed." if success else "Promptfoo result failed."
            )
        else:
            grading_result = _require_object(
                grading_result_value, f"{location}.gradingResult"
            )
            reason = grading_result.get("reason")
            details = reason if isinstance(reason, str) and reason else (
                error or ("Promptfoo result passed." if success else "Promptfoo result failed.")
            )
        _validate_json_value(grading_result, f"{location}.gradingResult")

        named_scores = _require_json_object(
            row.get("namedScores", {}), f"{location}.namedScores"
        )
        grader_metadata: JsonObject = {
            "source": "promptfoo",
            "test_idx": test_index,
            "prompt_idx": row_prompt_idx,
            "provider_id": row_provider_id,
            "grading_result": grading_result,
            "named_scores": named_scores,
        }
        if error:
            grader_metadata["error"] = error
        for field in ("failureReason", "tokenUsage", "traceId", "evaluationId"):
            if field in row and row[field] is not None:
                _validate_json_value(row[field], f"{location}.{field}")
                grader_metadata[field] = row[field]

        output = SystemOutput(
            case_id=case_id,
            output=output_value,
            latency_ms=latency,
            cost_usd=cost,
        )
        grader = GraderResult(
            grader="promptfoo",
            passed=success,
            score=score,
            details=details,
            metadata=grader_metadata,
        )
        cases.append(CaseResult(case=case, output=output, graders=(grader,)))

    evaluation_id = root.get("evalId")
    if evaluation_id is not None and not isinstance(evaluation_id, str):
        raise TypeError("evalId must be a string or null.")
    if run_id is not None:
        _require_nonempty_string(run_id, "run_id")
        resolved_run_id = run_id
    elif evaluation_id:
        resolved_run_id = f"promptfoo-{evaluation_id}"
    else:
        try:
            canonical_payload = json.dumps(
                root,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Promptfoo payload must contain only valid JSON values.") from exc
        digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()[:16]
        resolved_run_id = f"promptfoo-{digest}"

    manifest = RunMetadata(
        run_id=resolved_run_id,
        suite_version=suite_version,
        system_name=system_name,
        system_version=system_version,
        configuration={
            "source": "promptfoo",
            "promptfoo_result_version": result_version,
            "provider_id": selected_provider,
            "prompt_idx": selected_prompt,
            "prompt_ids": sorted(prompt_ids),
            "eval_id": evaluation_id,
        },
        seed=None,
        timestamp_utc=timestamp,
        environment={},
    )
    return EvaluationRun(manifest=manifest, cases=tuple(cases))


def load_promptfoo_json(
    path: str,
    *,
    system_name: str,
    system_version: str,
    suite_version: str,
    provider_id: str | None = None,
    prompt_idx: int | None = None,
    run_id: str | None = None,
) -> EvaluationRun:
    """Load a Promptfoo v3 JSON export from disk and normalize one system slice."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid Promptfoo JSON at line {exc.lineno}, column {exc.colno}."
        ) from exc
    return import_promptfoo_payload(
        payload,
        system_name=system_name,
        system_version=system_version,
        suite_version=suite_version,
        provider_id=provider_id,
        prompt_idx=prompt_idx,
        run_id=run_id,
    )


def _provider_id(value: Any, location: str) -> str:
    if isinstance(value, str):
        return _require_nonempty_string(value, location)
    provider = _require_object(value, location)
    return _require_nonempty_string(provider.get("id"), f"{location}.id")


def _tags(value: Any, location: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"{location} must be an array of strings.")
    tags = tuple(_require_nonempty_string(tag, location) for tag in value)
    if len(tags) != len(set(tags)):
        raise ValueError(f"{location} must not contain duplicate tags.")
    return tags


def _optional_nonnegative_number(value: Any, location: str) -> float | None:
    if value is None:
        return None
    number = _require_finite_number(value, location)
    if number < 0:
        raise ValueError(f"{location} must be non-negative.")
    return number


def _require_finite_number(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{location} must be numeric.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{location} must be finite.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{location} must be finite.")
    return number


def _require_index(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{location} must be a non-negative integer.")
    if value < 0:
        raise ValueError(f"{location} must be a non-negative integer.")
    return value


def _require_nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{location} must be a string.")
    if not value.strip():
        raise ValueError(f"{location} must not be empty.")
    return value


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
    raise TypeError(
        f"{location} contains a non-JSON value of type {type(value).__name__}."
    )
