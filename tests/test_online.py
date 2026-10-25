import math

import pytest

from ai_eval_engineering.online import (
    ABResultAdapter,
    Exposure,
    OnlineObservation,
    Outcome,
    build_metric_contract,
)


def test_online_contract_keeps_exposure_and_outcome_linked() -> None:
    exposure = Exposure("exp-1", "u-1", "control", "new-users")
    outcome = Outcome("exp-1", "u-1", "conversion", 1.0)
    observation = OnlineObservation(exposure, outcome)
    assert observation.exposure.variant == "control"
    assert observation.outcome.metric == "conversion"


def test_mismatched_experiment_is_rejected() -> None:
    with pytest.raises(ValueError):
        OnlineObservation(
            Exposure("exp-1", "u-1", "control", "all"),
            Outcome("exp-2", "u-1", "conversion", 1.0),
        )


def test_ab_adapter_compares_variants_with_independent_bootstrap() -> None:
    observations = [
        OnlineObservation(
            Exposure("exp-1", "u-1", "control", "all"),
            Outcome("exp-1", "u-1", "conversion", 0.0),
        ),
        OnlineObservation(
            Exposure("exp-1", "u-2", "control", "all"),
            Outcome("exp-1", "u-2", "conversion", 1.0),
        ),
        OnlineObservation(
            Exposure("exp-1", "u-3", "treatment", "all"),
            Outcome("exp-1", "u-3", "conversion", 1.0),
        ),
        OnlineObservation(
            Exposure("exp-1", "u-4", "treatment", "all"),
            Outcome("exp-1", "u-4", "conversion", 1.0),
        ),
    ]
    comparison = ABResultAdapter(observations).compare(
        "conversion", "control", "treatment", resamples=500, seed=7
    )
    assert comparison.baseline_sample_size == 2
    assert comparison.candidate_sample_size == 2
    assert comparison.mean_difference == 0.5
    assert comparison.confidence_interval is not None


def test_segment_comparisons_keep_segment_metrics_separate() -> None:
    observations = [
        OnlineObservation(
            Exposure("exp-1", "u-1", "new", "mobile"),
            Outcome("exp-1", "u-1", "conversion", 0.0),
        ),
        OnlineObservation(
            Exposure("exp-1", "u-2", "new", "desktop"),
            Outcome("exp-1", "u-2", "conversion", 0.0),
        ),
        OnlineObservation(
            Exposure("exp-1", "u-3", "old", "mobile"),
            Outcome("exp-1", "u-3", "conversion", 1.0),
        ),
        OnlineObservation(
            Exposure("exp-1", "u-4", "old", "desktop"),
            Outcome("exp-1", "u-4", "conversion", 1.0),
        ),
    ]
    comparisons = ABResultAdapter(observations).segment_comparisons(
        "conversion", "new", "old", resamples=500, seed=3
    )
    assert set(comparisons) == {"desktop", "mobile"}
    assert comparisons["mobile"].mean_difference == 1.0
    assert comparisons["mobile"].confidence_interval is None


def test_metric_contract_requires_one_experiment() -> None:
    exposures = [
        Exposure("exp-1", "u-1", "control", "all"),
        Exposure("exp-1", "u-2", "treatment", "all"),
    ]
    outcomes = [
        Outcome("exp-1", "u-1", "conversion", 0.0),
        Outcome("exp-1", "u-2", "conversion", 1.0),
    ]
    contract = build_metric_contract(exposures, outcomes, "conversion")
    assert contract.experiment_id == "exp-1"
    assert contract.exposure_count == 2
    assert contract.outcome_count == 2



@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_outcome_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        Outcome("exp-1", "u-1", "latency_ms", value)


def test_outcome_rejects_boolean_as_numeric_value() -> None:
    with pytest.raises(TypeError, match="numeric"):
        Outcome("exp-1", "u-1", "success", True)  # type: ignore[arg-type]


def test_exposure_rejects_non_string_identifiers() -> None:
    with pytest.raises(ValueError, match="experiment_id"):
        Exposure(None, "u-1", "control", "all")  # type: ignore[arg-type]


def test_metric_contract_rejects_non_integer_counts() -> None:
    from ai_eval_engineering.online import OnlineMetricContract

    with pytest.raises(ValueError, match="non-negative integers"):
        OnlineMetricContract("exp-1", "conversion", 1.5, 2)  # type: ignore[arg-type]
