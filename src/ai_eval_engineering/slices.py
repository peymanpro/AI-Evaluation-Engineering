"""Descriptive subgroup analysis for recorded AI evaluation runs."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from typing import TypeAlias

from .contracts import validate_grader_results
from .domain import CaseResult, EvaluationCase, EvaluationRun, GraderResult

SliceValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True)
class GraderSliceMetric:
    """Descriptive performance for one grader within a single slice."""

    grader: str
    case_count: int
    passed_cases: int
    pass_rate: float
    mean_score: float


@dataclass(frozen=True)
class SliceSummary:
    """Overall and per-grader metrics for one selected subgroup."""

    dimension: str
    value: SliceValue
    case_count: int
    passed_cases: int
    pass_rate: float
    mean_score: float
    meets_min_cases: bool
    grader_metrics: tuple[GraderSliceMetric, ...]


def analyze_run_slices(
    run: EvaluationRun,
    *,
    by: str,
    min_cases: int = 30,
    include_missing: bool = True,
) -> tuple[SliceSummary, ...]:
    """Summarize a recorded run by tag, risk category, or case metadata.

    Supported dimensions are "tag", "risk_category", and "metadata.<field>"
    for one top-level case-metadata field. Selecting "tag" intentionally places
    a case in each of its tags. Missing values form an explicit None slice by
    default so unclassified cases stay visible.

    The summaries are descriptive counts and means, not significance tests.
    "meets_min_cases" flags slices below the configured count; it never removes
    small slices from the returned evidence.
    """
    if not isinstance(run, EvaluationRun):
        raise TypeError("run must be an EvaluationRun.")
    if not isinstance(by, str) or not by.strip():
        raise ValueError("by must be 'tag', 'risk_category', or 'metadata.<field>'.")
    if by not in {"tag", "risk_category"} and not (
        by.startswith("metadata.") and by[len("metadata.") :].strip()
    ):
        raise ValueError("by must be 'tag', 'risk_category', or 'metadata.<field>'.")
    if isinstance(min_cases, bool) or not isinstance(min_cases, int):
        raise TypeError("min_cases must be an integer.")
    if min_cases < 1:
        raise ValueError("min_cases must be at least 1.")
    if not isinstance(include_missing, bool):
        raise TypeError("include_missing must be a boolean.")

    grouped: dict[str, tuple[SliceValue, list[CaseResult]]] = {}
    for index, result in enumerate(run.cases):
        if not isinstance(result, CaseResult):
            raise TypeError(f"run.cases[{index}] must be a CaseResult.")
        if not isinstance(result.case, EvaluationCase):
            raise TypeError(f"run.cases[{index}].case must be an EvaluationCase.")
        if not result.graders:
            raise ValueError(
                f"Case {result.case.id!r} has no grader results; "
                "slice analysis requires at least one grader per case."
            )
        validate_grader_results(tuple(result.graders), result.case.id)
        for value in _slice_values(result.case, by, include_missing):
            key = _value_key(value)
            if key not in grouped:
                grouped[key] = (value, [])
            grouped[key][1].append(result)

    summaries: list[SliceSummary] = []
    ordered_groups = sorted(grouped.values(), key=lambda item: _value_sort_key(item[0]))
    for value, case_results in ordered_groups:
        case_scores: list[float] = []
        passed_cases = 0
        grader_observations: dict[str, list[GraderResult]] = {}

        for case_result in case_results:
            graders = tuple(case_result.graders)
            if all(grader.passed for grader in graders):
                passed_cases += 1
            case_scores.append(statistics.fmean(float(grader.score) for grader in graders))
            for grader in graders:
                grader_observations.setdefault(grader.grader, []).append(grader)

        case_count = len(case_results)
        grader_metrics = tuple(
            GraderSliceMetric(
                grader=name,
                case_count=len(observations),
                passed_cases=sum(item.passed for item in observations),
                pass_rate=sum(item.passed for item in observations) / len(observations),
                mean_score=statistics.fmean(float(item.score) for item in observations),
            )
            for name, observations in sorted(grader_observations.items())
        )
        summaries.append(
            SliceSummary(
                dimension=by,
                value=value,
                case_count=case_count,
                passed_cases=passed_cases,
                pass_rate=passed_cases / case_count,
                mean_score=statistics.fmean(case_scores),
                meets_min_cases=case_count >= min_cases,
                grader_metrics=grader_metrics,
            )
        )
    return tuple(summaries)


def _slice_values(
    case: EvaluationCase,
    dimension: str,
    include_missing: bool,
) -> tuple[SliceValue, ...]:
    if dimension == "tag":
        values: list[SliceValue] = list(case.tags)
        if not values and include_missing:
            values.append(None)
    elif dimension == "risk_category":
        values = [case.risk_category]
    else:
        field = dimension[len("metadata.") :]
        values = [case.metadata.get(field)]

    normalized: dict[str, SliceValue] = {}
    for value in values:
        if value is None:
            if include_missing:
                normalized[_value_key(None)] = None
            continue
        if isinstance(value, bool):
            normalized[_value_key(value)] = value
            continue
        if isinstance(value, str):
            normalized[_value_key(value)] = value
            continue
        if isinstance(value, int):
            normalized[_value_key(value)] = value
            continue
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(
                    f"Slice value for case {case.id!r} in {dimension!r} must be finite."
                )
            normalized[_value_key(value)] = value
            continue
        raise TypeError(
            f"Slice value for case {case.id!r} in {dimension!r} must be a JSON scalar; "
            f"got {type(value).__name__}."
        )
    return tuple(
        normalized[key]
        for key in sorted(
            normalized,
            key=lambda item_key: _value_sort_key(normalized[item_key]),
        )
    )


def _value_key(value: SliceValue) -> str:
    """Create a deterministic key; bool, int, and float remain distinct."""
    return f"{type(value).__name__}:{json.dumps(value, ensure_ascii=False, allow_nan=False)}"


def _value_sort_key(value: SliceValue) -> tuple[str, str]:
    return (type(value).__name__, json.dumps(value, ensure_ascii=False, allow_nan=False))
