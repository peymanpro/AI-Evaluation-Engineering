from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ai_eval_engineering import (
    AsyncEvaluationRunner,
    CheckpointError,
    EvaluationCase,
    EvaluationRunner,
    EvaluationSuite,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


def make_suite() -> EvaluationSuite:
    return EvaluationSuite(
        "checkpoint-suite-v1",
        tuple(
            EvaluationCase(case_id, {"question": f"question {case_id}"}, expected=f"answer-{case_id}")
            for case_id in ("first", "flaky", "last")
        ),
    )


def make_manifest(suite: EvaluationSuite, system_version: str = "revision-1"):
    return build_run_metadata(
        suite,
        "checkpoint-test-system",
        system_version,
        {"adapter": "deterministic-fixture"},
        seed=17,
    )


class FailCaseOnceAdapter:
    def __init__(self, failing_case: str | None) -> None:
        self.failing_case = failing_case
        self.calls: list[str] = []

    def run(self, case: EvaluationCase) -> SystemOutput:
        self.calls.append(case.id)
        if case.id == self.failing_case:
            raise RuntimeError(f"temporary failure at {case.id}")
        return SystemOutput(case.id, case.expected, latency_ms=2.0, cost_usd=0.01)


class AsyncFailCaseOnceAdapter:
    def __init__(self, failing_case: str | None) -> None:
        self.failing_case = failing_case
        self.calls: list[str] = []

    async def run(self, case: EvaluationCase) -> SystemOutput:
        await asyncio.sleep(0)
        self.calls.append(case.id)
        if case.id == self.failing_case:
            raise RuntimeError(f"temporary async failure at {case.id}")
        return SystemOutput(case.id, case.expected, latency_ms=2.0, cost_usd=0.01)


def test_sync_runner_resumes_only_unfinished_cases(tmp_path: Path) -> None:
    suite = make_suite()
    first_manifest = make_manifest(suite)
    checkpoint = tmp_path / "runs" / "checkpoint.json"
    first_adapter = FailCaseOnceAdapter("flaky")
    runner = EvaluationRunner(first_adapter, [ExactMatchGrader()])

    with pytest.raises(RuntimeError, match="temporary failure at flaky"):
        runner.run(suite, first_manifest, checkpoint_path=checkpoint)

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["checkpoint_version"] == 1
    assert len(saved["run"]["cases"]) == 1
    assert first_adapter.calls == ["first", "flaky"]

    resume_manifest = make_manifest(suite)
    resumed_adapter = FailCaseOnceAdapter(None)
    resumed = EvaluationRunner(resumed_adapter, [ExactMatchGrader()]).run(
        suite,
        resume_manifest,
        checkpoint_path=checkpoint,
    )

    assert resumed.manifest.run_id == first_manifest.run_id
    assert [row.case.id for row in resumed.cases] == ["first", "flaky", "last"]
    assert all(row.graders[0].passed for row in resumed.cases)
    assert resumed_adapter.calls == ["flaky", "last"]


def test_completed_checkpoint_is_reused_without_reexecuting_cases(tmp_path: Path) -> None:
    suite = make_suite()
    checkpoint = tmp_path / "complete.json"
    first = EvaluationRunner(FailCaseOnceAdapter(None), [ExactMatchGrader()]).run(
        suite,
        make_manifest(suite),
        checkpoint_path=checkpoint,
    )
    second_adapter = FailCaseOnceAdapter(None)

    second = EvaluationRunner(second_adapter, [ExactMatchGrader()]).run(
        suite,
        make_manifest(suite),
        checkpoint_path=checkpoint,
    )

    assert second_adapter.calls == []
    assert second == first


def test_checkpoint_refuses_changed_suite_definition(tmp_path: Path) -> None:
    original = make_suite()
    checkpoint = tmp_path / "suite.json"
    EvaluationRunner(FailCaseOnceAdapter(None), [ExactMatchGrader()]).run(
        original,
        make_manifest(original),
        checkpoint_path=checkpoint,
    )
    changed_case = EvaluationCase(
        "first",
        {"question": "changed question"},
        expected="answer-first",
    )
    changed_suite = EvaluationSuite(
        original.version,
        (changed_case, *original.cases[1:]),
    )
    adapter = FailCaseOnceAdapter(None)

    with pytest.raises(CheckpointError, match="fingerprint"):
        EvaluationRunner(adapter, [ExactMatchGrader()]).run(
            changed_suite,
            make_manifest(changed_suite),
            checkpoint_path=checkpoint,
        )

    assert adapter.calls == []


def test_checkpoint_refuses_changed_system_identity(tmp_path: Path) -> None:
    suite = make_suite()
    checkpoint = tmp_path / "identity.json"
    EvaluationRunner(FailCaseOnceAdapter(None), [ExactMatchGrader()]).run(
        suite,
        make_manifest(suite),
        checkpoint_path=checkpoint,
    )

    with pytest.raises(CheckpointError, match="system_version"):
        EvaluationRunner(FailCaseOnceAdapter(None), [ExactMatchGrader()]).run(
            suite,
            make_manifest(suite, system_version="revision-2"),
            checkpoint_path=checkpoint,
        )


def test_corrupt_checkpoint_is_not_silently_discarded(tmp_path: Path) -> None:
    suite = make_suite()
    checkpoint = tmp_path / "corrupt.json"
    checkpoint.write_text("{broken", encoding="utf-8")
    adapter = FailCaseOnceAdapter(None)

    with pytest.raises(CheckpointError, match="Could not read"):
        EvaluationRunner(adapter, [ExactMatchGrader()]).run(
            suite,
            make_manifest(suite),
            checkpoint_path=checkpoint,
        )

    assert adapter.calls == []


def test_async_runner_resumes_only_unfinished_cases(tmp_path: Path) -> None:
    suite = make_suite()
    checkpoint = tmp_path / "async.json"
    first_adapter = AsyncFailCaseOnceAdapter("flaky")
    first_runner = AsyncEvaluationRunner(
        first_adapter,
        [ExactMatchGrader()],
        max_concurrency=1,
    )

    with pytest.raises(RuntimeError, match="temporary async failure at flaky"):
        asyncio.run(
            first_runner.run(
                suite,
                make_manifest(suite),
                checkpoint_path=checkpoint,
            )
        )

    assert first_adapter.calls == ["first", "flaky"]
    resumed_adapter = AsyncFailCaseOnceAdapter(None)
    resumed_runner = AsyncEvaluationRunner(
        resumed_adapter,
        [ExactMatchGrader()],
        max_concurrency=1,
    )
    resumed = asyncio.run(
        resumed_runner.run(
            suite,
            make_manifest(suite),
            checkpoint_path=checkpoint,
        )
    )

    assert [row.case.id for row in resumed.cases] == ["first", "flaky", "last"]
    assert all(row.graders[0].passed for row in resumed.cases)
    assert resumed_adapter.calls == ["flaky", "last"]
