"""Machine-readable and human-readable evaluation reports."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .domain import AggregatedResult, EvaluationRun
from .regression import GateResult
from .statistics import ConfidenceInterval, PairedComparison, VarianceReport


def build_report(
    run: EvaluationRun,
    aggregate: AggregatedResult,
    confidence_interval: ConfidenceInterval | None = None,
    gate: GateResult | None = None,
    paired: PairedComparison | None = None,
    variance: VarianceReport | None = None,
) -> dict[str, Any]:
    return {
        "manifest": _to_dict(run.manifest),
        "summary": _to_dict(aggregate),
        "confidence_interval": _to_dict(confidence_interval),
        "gate": _to_dict(gate),
        "paired_comparison": _to_dict(paired),
        "variance": _to_dict(variance),
        "cases": [_to_dict(result) for result in run.cases],
    }


def write_json_report(report: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def render_markdown(report: dict[str, Any]) -> str:
    manifest = report["manifest"]
    summary = report["summary"]
    lines = [
        "# Evaluation Report",
        "",
        f"- System: {manifest['system_name']}@{manifest['system_version']}",
        f"- Suite: {manifest['suite_version']}",
        f"- Run: {manifest['run_id']}",
        f"- Cases: {summary['total_cases']}",
        f"- Pass rate: {summary['pass_rate']:.2%}",
        f"- Mean score: {summary['mean_score']:.4f}",
        "",
    ]
    ci = report.get("confidence_interval")
    if ci:
        lines.extend([
            "## Uncertainty",
            "",
            (
                f"Bootstrap mean CI: [{ci['lower']:.4f}, {ci['upper']:.4f}] "
                f"({ci['confidence']:.0%}, {ci['resamples']} resamples)."
            ),
            "",
        ])
    gate = report.get("gate")
    if gate:
        lines.extend(["## Release Gate", "", str(gate.get("summary", gate)), ""])
    lines.extend([
        "## Limitations",
        "",
        "This report is evidence for the evaluated suite only; it is not a "
        "production-wide quality claim.",
        "",
    ])
    return "\n".join(lines)


def write_markdown_report(report: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(render_markdown(report), encoding="utf-8")


def _to_dict(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        result = {key: _to_dict(item) for key, item in asdict(value).items()}
        if isinstance(value, GateResult):
            result["summary"] = value.summary()
        return result
    if isinstance(value, tuple):
        return [_to_dict(item) for item in value]
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_dict(item) for key, item in value.items()}
    return value
