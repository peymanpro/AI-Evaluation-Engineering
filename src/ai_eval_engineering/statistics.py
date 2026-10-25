"""Small, auditable statistical utilities for AI evaluation results."""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceInterval:
    estimate: float
    lower: float
    upper: float
    confidence: float
    resamples: int


@dataclass(frozen=True)
class PairedComparison:
    baseline_mean: float
    candidate_mean: float
    mean_difference: float
    standardized_effect: float | None
    sample_size: int


@dataclass(frozen=True)
class VarianceReport:
    runs: int
    mean: float
    sample_variance: float
    standard_deviation: float
    min_value: float
    max_value: float


def bootstrap_mean_ci(
    values: list[float],
    confidence: float = 0.95,
    resamples: int = 2000,
    seed: int = 0,
) -> ConfidenceInterval:
    """Estimate a percentile-bootstrap confidence interval for an independent sample."""
    checked = _validate_values(values, name="values")
    _validate_bootstrap_options(confidence, resamples)
    if len(checked) < 2:
        raise ValueError("At least two observations are required to estimate uncertainty.")
    rng = random.Random(seed)
    samples = [
        statistics.fmean(rng.choices(checked, k=len(checked)))
        for _ in range(resamples)
    ]
    samples.sort()
    alpha = (1.0 - confidence) / 2.0
    return ConfidenceInterval(
        estimate=statistics.fmean(checked),
        lower=_quantile(samples, alpha),
        upper=_quantile(samples, 1.0 - alpha),
        confidence=confidence,
        resamples=resamples,
    )


def paired_compare(baseline: list[float], candidate: list[float]) -> PairedComparison:
    baseline_checked = _validate_values(baseline, name="baseline")
    candidate_checked = _validate_values(candidate, name="candidate")
    if not baseline_checked or not candidate_checked:
        raise ValueError("Both populations require at least one value.")
    if len(baseline_checked) != len(candidate_checked):
        raise ValueError("Paired comparison requires equal population sizes.")
    differences = [
        c - b for b, c in zip(baseline_checked, candidate_checked, strict=True)
    ]
    diff_mean = statistics.fmean(differences)
    if len(differences) < 2:
        effect: float | None = None
    else:
        sd = statistics.stdev(differences)
        # A standardized effect is undefined when the observed paired
        # differences have no variance; reporting zero would imply no effect.
        effect = diff_mean / sd if sd else None
    return PairedComparison(
        baseline_mean=statistics.fmean(baseline_checked),
        candidate_mean=statistics.fmean(candidate_checked),
        mean_difference=diff_mean,
        standardized_effect=effect,
        sample_size=len(differences),
    )


def bootstrap_difference_ci(
    baseline: list[float],
    candidate: list[float],
    confidence: float = 0.95,
    resamples: int = 2000,
    seed: int = 0,
) -> ConfidenceInterval:
    """Estimate a difference CI for two independent samples.

    For measurements paired by case or prompt, independently resampling these
    populations is not appropriate; use a paired analysis instead.
    """
    baseline_checked = _validate_values(baseline, name="baseline")
    candidate_checked = _validate_values(candidate, name="candidate")
    _validate_bootstrap_options(confidence, resamples)
    if len(baseline_checked) < 2 or len(candidate_checked) < 2:
        raise ValueError("At least two observations per group are required to estimate uncertainty.")
    rng = random.Random(seed)
    differences = [
        statistics.fmean(rng.choices(candidate_checked, k=len(candidate_checked)))
        - statistics.fmean(rng.choices(baseline_checked, k=len(baseline_checked)))
        for _ in range(resamples)
    ]
    differences.sort()
    alpha = (1.0 - confidence) / 2.0
    return ConfidenceInterval(
        estimate=statistics.fmean(candidate_checked) - statistics.fmean(baseline_checked),
        lower=_quantile(differences, alpha),
        upper=_quantile(differences, 1.0 - alpha),
        confidence=confidence,
        resamples=resamples,
    )


def variance_report(values: list[float]) -> VarianceReport:
    checked = _validate_values(values, name="values")
    if not checked:
        raise ValueError("At least one value is required.")
    sample_variance = statistics.variance(checked) if len(checked) > 1 else 0.0
    return VarianceReport(
        runs=len(checked),
        mean=statistics.fmean(checked),
        sample_variance=sample_variance,
        standard_deviation=math.sqrt(sample_variance),
        min_value=min(checked),
        max_value=max(checked),
    )


def _validate_values(values: list[float], *, name: str) -> list[float]:
    checked: list[float] = []
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}[{index}] must be a finite number.")
        try:
            converted = float(value)
        except OverflowError as exc:
            raise ValueError(f"{name}[{index}] must be a finite number.") from exc
        if not math.isfinite(converted):
            raise ValueError(f"{name}[{index}] must be a finite number.")
        checked.append(converted)
    return checked


def _validate_bootstrap_options(confidence: float, resamples: int) -> None:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a finite number between 0 and 1.")
    try:
        confidence_value = float(confidence)
    except OverflowError as exc:
        raise ValueError("confidence must be a finite number between 0 and 1.") from exc
    if not math.isfinite(confidence_value) or not 0.0 < confidence_value < 1.0:
        raise ValueError("confidence must be a finite number between 0 and 1.")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 100:
        raise ValueError("resamples must be an integer of at least 100.")


def _quantile(sorted_values: list[float], q: float) -> float:
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction
