import pytest

from ai_eval_engineering.statistics import bootstrap_mean_ci, paired_compare, variance_report


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
    assert comparison.standardized_effect > 0
    report = variance_report([0.7, 0.8, 0.9])
    assert report.runs == 3
    assert report.standard_deviation > 0
