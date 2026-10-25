from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_eval_engineering.domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from ai_eval_engineering.failure_memory import (
    build_failure_regression_suite,
    extract_failure_records,
    merge_failure_memory,
    read_failure_memory,
    write_failure_memory,
)


def make_run(
    run_id: str,
    system_version: str,
    *,
    failed_indices: tuple[int, ...] = (1,),
    prompt_prefix: str = "question",
    case_ids: tuple[str, ...] = ("case-0", "case-1", "case-2"),
    output_marker: str = "observed-output-secret",
    invalid_score: float | None = None,
) -> EvaluationRun:
    cases = []
    for index, case_id in enumerate(case_ids):
        case = EvaluationCase(
            id=case_id,
            input={"prompt": f"{prompt_prefix} {index}"},
            expected={"answer": f"expected {index}"},
            metadata={"source": "unit-test"},
            tags=("release-test",),
            risk_category="tool_abuse" if index in failed_indices else None,
        )
        output = SystemOutput(
            case_id=case_id,
            output={"answer": f"{output_marker}-{index}"},
        )
        failed = index in failed_indices
        score = invalid_score if invalid_score is not None and failed else (0.25 if failed else 0.9)
        quality = GraderResult(
            grader="quality",
            passed=not failed,
            score=score,
            details="quality below target" if failed else "quality accepted",
        )
        schema = GraderResult(
            grader="schema",
            passed=True,
            score=1.0,
            details="schema valid",
        )
        cases.append(CaseResult(case, output, (quality, schema)))
    return EvaluationRun(
        manifest=RunMetadata(
            run_id=run_id,
            suite_version="suite-v1",
            system_name="example-assistant",
            system_version=system_version,
            configuration={},
            seed=13,
            timestamp_utc="2026-10-25T12:00:00Z",
        ),
        cases=tuple(cases),
    )


def test_extracts_only_failed_graders_and_keeps_original_case() -> None:
    run = make_run("run-1", "v1", failed_indices=(1, 2))
    records = extract_failure_records(run)

    assert len(records) == 2
    assert {record.case.id for record in records} == {"case-1", "case-2"}
    assert {record.grader for record in records} == {"quality"}
    assert all(record.seen_run_ids == ("run-1",) for record in records)
    assert records[0].case.input["prompt"].startswith("question")
    assert records[0].case.risk_category == "tool_abuse"


def test_no_failed_graders_produces_empty_memory() -> None:
    assert extract_failure_records(make_run("run-1", "v1", failed_indices=())) == ()


def test_failure_identity_is_stable_across_system_versions() -> None:
    first = extract_failure_records(make_run("run-1", "v1"))[0]
    second = extract_failure_records(make_run("run-2", "v2"))[0]

    assert first.failure_id == second.failure_id
    assert first.latest_score == 0.25
    assert second.latest_score == 0.25


def test_merge_tracks_recurrence_without_duplicate_run_ids() -> None:
    first = extract_failure_records(make_run("run-1", "v1"))[0]
    second = extract_failure_records(make_run("run-2", "v2"))[0]

    merged = merge_failure_memory((first,), (second, second))

    assert len(merged) == 1
    assert merged[0].first_seen_run_id == "run-1"
    assert merged[0].last_seen_run_id == "run-2"
    assert merged[0].seen_run_ids == ("run-1", "run-2")
    assert merged[0].system_version == "v2"


def test_jsonl_memory_round_trips_and_does_not_store_model_output(tmp_path: Path) -> None:
    records = extract_failure_records(make_run("run-1", "v1"))
    path = tmp_path / "nested" / "failure-memory.jsonl"

    written = write_failure_memory(records, path)
    loaded = read_failure_memory(path)

    assert written == path
    assert loaded == records
    assert "observed-output-secret" not in path.read_text(encoding="utf-8")
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["schema_version"] == 1
    assert "output" not in payload


def test_failure_memory_builds_deduplicated_regression_suite() -> None:
    run = make_run("run-1", "v1", failed_indices=(1,))
    records = extract_failure_records(run)
    # Add another failing grader for the same source case.
    source = run.cases[1]
    extra = GraderResult("safety", False, 0.0, "policy violation")
    extra_run = EvaluationRun(
        run.manifest,
        tuple(
            CaseResult(item.case, item.output, item.graders + (extra,))
            if item.case.id == source.case.id
            else item
            for item in run.cases
        ),
    )
    records = extract_failure_records(extra_run)

    suite = build_failure_regression_suite(records, version="regression-v1")

    assert suite.version == "regression-v1"
    assert len(suite.cases) == 1
    assert suite.cases[0].id == "case-1"


def test_conflicting_definitions_for_same_case_id_are_not_silently_merged() -> None:
    first = extract_failure_records(make_run("run-1", "v1", prompt_prefix="old"))[0]
    second = extract_failure_records(make_run("run-2", "v2", prompt_prefix="new"))[0]

    with pytest.raises(ValueError, match="Different case definitions"):
        build_failure_regression_suite((first, second), version="regression-v1")


def test_duplicate_case_ids_in_run_are_rejected() -> None:
    run = make_run("run-1", "v1", case_ids=("same", "same", "other"))

    with pytest.raises(ValueError, match="duplicate case id"):
        extract_failure_records(run)


def test_non_finite_failed_score_is_rejected() -> None:
    run = make_run("run-1", "v1", invalid_score=float("nan"))

    with pytest.raises(ValueError, match="finite"):
        extract_failure_records(run)


def test_memory_reader_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "future.jsonl"
    path.write_text('{"schema_version":99}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported schema_version"):
        read_failure_memory(path)


def test_writer_rejects_duplicate_failure_ids(tmp_path: Path) -> None:
    record = extract_failure_records(make_run("run-1", "v1"))[0]

    with pytest.raises(ValueError, match="duplicate failure ids"):
        write_failure_memory((record, record), tmp_path / "duplicates.jsonl")



def test_reader_rejects_tampered_failure_identity(tmp_path: Path) -> None:
    record = extract_failure_records(make_run("run-1", "v1"))[0]
    path = tmp_path / "tampered.jsonl"
    write_failure_memory((record,), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["failure_id"] = "tampered-id"
    path.write_text(json.dumps(payload) + "\\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stable identity"):
        read_failure_memory(path)
