import pytest

from ai_eval_engineering.online import (
    Exposure,
    Outcome,
    OnlineObservation,
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
