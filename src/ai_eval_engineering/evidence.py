"""Auditable evidence-package writer for evaluation runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import EvaluationRun
from .report import render_markdown


def _jsonify(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonify(item) for key, item in vars(value).items()}
    if isinstance(value, tuple):
        return [_jsonify(item) for item in value]
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    return value


def write_evidence_package(
    run: EvaluationRun,
    report: dict[str, Any],
    configuration: dict[str, Any],
    directory: str | Path,
) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)

    (root / "manifest.json").write_text(
        json.dumps(_jsonify(run.manifest), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "raw-results.json").write_text(
        json.dumps(
            {"cases": [_jsonify(item) for item in run.cases]},
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "configuration.json").write_text(
        json.dumps(configuration, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return root
