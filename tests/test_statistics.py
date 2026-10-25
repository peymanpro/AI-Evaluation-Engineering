import math

import pytest

from ai_eval_engineering.statistics import (
    bootstrap_difference_ci,
    bootstrap_mean_ci,
    paired_compare,
    variance_report,
)


def test_bootstrap_ci_is_reproducible() -> None:
    values = [0.8, 0.9, 1.0, 0.7]
    first = bootstrap_mean_ci(values, seed=42, resamples=500)
    second = bootstrap_mean_ci(values, seed=42, resamples=500)
    assert first == second
    assert first.lower <= first.estimate <= first.upper


def test_paired_comparison_rejects_mismatch() -> None:
    with pytest.raises(ValueError):
        paired_compare([1.0], [1.0, 2.0])


def test_paired_effect_and_variance() -> None:
    comparison = paired_compare([0.7, 0.8, 0.9], [0.8, 0.9, 1.0])
    assert comparison.mean_difference == pytest.approx(0.1)
    assert comparison.standardized_effect is not None
    assert comparison.standardized_effect > 0
    report = variance_report([0.7, 0.8, 0.9])
    assert report.runs == 3
    assert report.standard_deviation > 0


def test_standardized_effect_is_undefined_for_constant_paired_differences() -> None:
    comparison = paired_compare([1.0, 2.0, 3.0], [2.0, 3.0, 4.0])
    assert comparison.mean_difference == pytest.approx(1.0)
    assert comparison.standardized_effect is None


@pytest.mark.parametrize(
    "operation",
    [
        lambda values: bootstrap_mean_ci(values, resamples=500),
        lambda values: variance_report(values),
        lambda values: paired_compare(values, [0.0, 0.0]),
        lambda values: bootstrap_difference_ci(values, [0.0, 1.0], resamples=500),
    ],
)
def test_statistical_functions_reject_non_finite_values(operation) -> None:
    with pytest.raises(ValueError, match="finite"):
        operation([0.0, math.nan])


def test_confidence_interval_requires_multiple_observations() -> None:
    with pytest.raises(ValueError, match="At least two"):
        bootstrap_mean_ci([0.7])


def test_independent_difference_ci_requires_multiple_observations_per_group() -> None:
    with pytest.raises(ValueError, match="two observations per group"):
        bootstrap_difference_ci([0.7], [0.8, 0.9], resamples=500)


def test_paired_comparison_rejects_empty_populations() -> None:
    with pytest.raises(ValueError, match="at least one"):
        paired_compare([], [])


def test_bootstrap_rejects_non_integer_resample_count() -> None:
    with pytest.raises(TypeError, match="integer"):
        bootstrap_mean_ci([0.7, 0.8], resamples=100.5)  # type: ignore[arg-type]
