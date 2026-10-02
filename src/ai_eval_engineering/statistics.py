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
    standardized_effect: float
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
    if not values:
        raise ValueError("At least one value is required.")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1.")
    if resamples < 100:
        raise ValueError("resamples must be at least 100.")
    rng = random.Random(seed)
    samples = [
        statistics.fmean(rng.choices(values, k=len(values)))
        for _ in range(resamples)
    ]
    samples.sort()
    alpha = (1.0 - confidence) / 2.0
    return ConfidenceInterval(
        estimate=statistics.fmean(values),
        lower=_quantile(samples, alpha),
        upper=_quantile(samples, 1.0 - alpha),
        confidence=confidence,
        resamples=resamples,
    )


def paired_compare(baseline: list[float], candidate: list[float]) -> PairedComparison:
    if not baseline or not candidate:
        raise ValueError("Both populations require at least one value.")
    if len(baseline) != len(candidate):
        raise ValueError("Paired comparison requires equal population sizes.")
    differences = [c - b for b, c in zip(baseline, candidate, strict=True)]
    diff_mean = statistics.fmean(differences)
    if len(differences) < 2:
        effect = 0.0
    else:
        sd = statistics.stdev(differences)
        effect = diff_mean / sd if sd else 0.0
    return PairedComparison(
        baseline_mean=statistics.fmean(baseline),
        candidate_mean=statistics.fmean(candidate),
        mean_difference=diff_mean,
        standardized_effect=effect,
        sample_size=len(differences),
    )


def variance_report(values: list[float]) -> VarianceReport:
    if not values:
        raise ValueError("At least one value is required.")
    sample_variance = statistics.variance(values) if len(values) > 1 else 0.0
    return VarianceReport(
        runs=len(values),
        mean=statistics.fmean(values),
        sample_variance=sample_variance,
        standard_deviation=math.sqrt(sample_variance),
        min_value=min(values),
        max_value=max(values),
    )


def _quantile(sorted_values: list[float], q: float) -> float:
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction
