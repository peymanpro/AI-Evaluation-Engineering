"""Deterministic dataset loading and regression-case management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import EvaluationCase, EvaluationSuite


def load_suite(path: str | Path) -> EvaluationSuite:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Dataset root must be an object.")
    version = payload.get("version")
    cases = payload.get("cases")
    if not isinstance(version, str) or not version:
        raise ValueError("Dataset version must be a non-empty string.")
    if not isinstance(cases, list):
        raise TypeError("Dataset cases must be a list.")

    parsed: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    for raw in cases:
        if not isinstance(raw, dict):
            raise TypeError("Each evaluation case must be an object.")
        case_id = raw.get("id")
        case_input = raw.get("input")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("Each case needs a non-empty id.")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate case id: {case_id}")
        if not isinstance(case_input, dict):
            raise TypeError(f"Case {case_id} input must be an object.")
        tags = raw.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
            raise ValueError(f"Case {case_id} tags must be strings.")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"Case {case_id} metadata must be an object.")
        seen_ids.add(case_id)
        parsed.append(
            EvaluationCase(
                id=case_id,
                input=case_input,
                expected=raw.get("expected"),
                metadata=metadata,
                tags=tuple(tags),
                risk_category=raw.get("risk_category"),
            )
        )
    return EvaluationSuite(version=version, cases=tuple(parsed))


def save_suite(suite: EvaluationSuite, path: str | Path) -> None:
    payload: dict[str, Any] = {
        "version": suite.version,
        "cases": [
            {
                "id": case.id,
                "input": case.input,
                "expected": case.expected,
                "metadata": case.metadata,
                "tags": list(case.tags),
                "risk_category": case.risk_category,
            }
            for case in suite.cases
        ],
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def promote_regression_case(
    suite: EvaluationSuite,
    case: EvaluationCase,
    path: str | Path,
) -> EvaluationSuite:
    """Persist a known failure as a new regression suite case.

    The original suite is left untouched; the returned suite is suitable for
    saving as a versioned regression suite.
    """
    if any(existing.id == case.id for existing in suite.cases):
        raise ValueError(f"Case id already exists: {case.id}")
    regression_case = EvaluationCase(
        id=case.id,
        input=case.input,
        expected=case.expected,
        metadata={**case.metadata, "promoted_from": suite.version},
        tags=tuple(sorted(set(case.tags) | {"regression"})),
        risk_category=case.risk_category or "regression",
    )
    regression_suite = EvaluationSuite(
        version=f"{suite.version}+regression",
        cases=(*suite.cases, regression_case),
    )
    save_suite(regression_suite, path)
    return regression_suite
