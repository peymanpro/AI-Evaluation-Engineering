from ai_eval_engineering.evidence_guardrails import assess_online_evidence
from ai_eval_engineering.online import Exposure, Outcome


def observations() -> tuple[list[Exposure], list[Outcome]]:
    exposures = [
        Exposure("exp-1", "u-1", "control", "all"),
        Exposure("exp-1", "u-2", "treatment", "all"),
    ]
    outcomes = [
        Outcome("exp-1", "u-1", "conversion", 0.0),
        Outcome("exp-1", "u-2", "conversion", 1.0),
    ]
    return exposures, outcomes


def test_small_samples_surface_insufficient_evidence() -> None:
    exposures, outcomes = observations()
    assessment = assess_online_evidence(
        exposures, outcomes, "conversion", min_sample_size=3
    )
    assert not assessment.sufficient
    assert assessment.issues[0].code == "insufficient_sample"


def test_ground_truth_and_selection_bias_are_explicit() -> None:
    exposures, outcomes = observations()
    assessment = assess_online_evidence(
        exposures,
        outcomes,
        "conversion",
        min_sample_size=1,
        require_ground_truth=True,
        ground_truth_available=False,
        selection_bias_detected=True,
    )
    codes = {issue.code for issue in assessment.issues}
    assert codes == {"missing_ground_truth", "selection_bias"}


def test_missing_outcome_is_not_hidden() -> None:
    exposures, outcomes = observations()
    assessment = assess_online_evidence(
        exposures,
        outcomes[:1],
        "conversion",
        min_sample_size=1,
    )
    assert "missing_outcome" in {issue.code for issue in assessment.issues}


def test_overlapping_population_is_rejected() -> None:
    exposures, outcomes = observations()
    exposures.append(Exposure("exp-1", "u-1", "treatment", "all"))
    assessment = assess_online_evidence(
        exposures,
        outcomes,
        "conversion",
        min_sample_size=1,
    )
    assert "overlapping_population" in {issue.code for issue in assessment.issues}
