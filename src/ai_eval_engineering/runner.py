"""Evaluation adapters and deterministic suite execution."""

from __future__ import annotations

import hashlib
import json
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    GraderResult,
    JsonObject,
    RunMetadata,
    SystemOutput,
)


class SystemAdapter(Protocol):
    def run(self, case: EvaluationCase) -> SystemOutput:
        ...


class Grader(Protocol):
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        ...


def configuration_hash(configuration: JsonObject) -> str:
    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def build_run_metadata(
    suite: EvaluationSuite,
    system_name: str,
    system_version: str,
    configuration: JsonObject | None = None,
    seed: int | None = None,
) -> RunMetadata:
    config = configuration or {}
    return RunMetadata(
        run_id=str(uuid.uuid4()),
        suite_version=suite.version,
        system_name=system_name,
        system_version=system_version,
        configuration={**config, "configuration_hash": configuration_hash(config)},
        seed=seed,
        timestamp_utc=datetime.now(UTC).isoformat(),
        environment={"python": platform.python_version(), "platform": platform.platform()},
    )


class EvaluationRunner:
    def __init__(self, adapter: SystemAdapter, graders: list[Grader]) -> None:
        if not graders:
            raise ValueError("At least one grader is required.")
        self._adapter = adapter
        self._graders = graders

    def run(self, suite: EvaluationSuite, manifest: RunMetadata) -> EvaluationRun:
        results: list[CaseResult] = []
        for case in suite.cases:
            output = self._adapter.run(case)
            if output.case_id != case.id:
                raise ValueError(
                    f"System returned case id {output.case_id!r} for expected {case.id!r}."
                )
            grader_results = tuple(grader.grade(case, output) for grader in self._graders)
            results.append(CaseResult(case=case, output=output, graders=grader_results))
        return EvaluationRun(manifest=manifest, cases=tuple(results))


def persist_run(run: EvaluationRun, path: str | Path) -> None:
    payload = {
        "manifest": _jsonify(run.manifest),
        "cases": [_jsonify(result) for result in run.cases],
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _jsonify(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonify(field) for key, field in vars(value).items()}
    if isinstance(value, tuple):
        return [_jsonify(item) for item in value]
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    return value
