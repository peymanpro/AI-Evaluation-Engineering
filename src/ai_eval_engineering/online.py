"""Provider-neutral contracts for online AI evaluation observations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .statistics import ConfidenceInterval, bootstrap_difference_ci

OnlineValue = int | float
EvidenceState = Literal["sufficient", "insufficient"]


@dataclass(frozen=True)
class Exposure:
    experiment_id: str
    exposure_id: str
    variant: str
    segment: str

    def __post_init__(self) -> None:
        for name, value in (
            ("experiment_id", self.experiment_id),
            ("exposure_id", self.exposure_id),
            ("variant", self.variant),
            ("segment", self.segment),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be empty.")


@dataclass(frozen=True)
class Outcome:
    experiment_id: str
    exposure_id: str
    metric: str
    value: OnlineValue

    def __post_init__(self) -> None:
        for name, value in (
            ("experiment_id", self.experiment_id),
            ("exposure_id", self.exposure_id),
            ("metric", self.metric),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be empty.")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("Outcome value must be numeric.")


@dataclass(frozen=True)
class OnlineObservation:
    exposure: Exposure
    outcome: Outcome

    def __post_init__(self) -> None:
        if self.exposure.experiment_id != self.outcome.experiment_id:
            raise ValueError("Exposure and outcome must belong to the same experiment.")
        if self.exposure.exposure_id != self.outcome.exposure_id:
            raise ValueError("Exposure and outcome must share an exposure id.")


@dataclass(frozen=True)
class VariantMetrics:
    variant: str
    metric: str
    values: tuple[OnlineValue, ...]
    
    @property
    def sample_size(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        if not self.values:
            raise ValueError("Variant requires at least one outcome.")
        return sum(self.values) / len(self.values)


@dataclass(frozen=True)
class OnlineVariantComparison:
    metric: str
    baseline_variant: str
    candidate_variant: str
    baseline_sample_size: int
    candidate_sample_size: int
    baseline_mean: float
    candidate_mean: float
    mean_difference: float
    confidence_interval: ConfidenceInterval


class ABResultAdapter:
    """Aggregate online outcomes by experiment variant without vendor coupling."""

    def __init__(self, observations: list[OnlineObservation]) -> None:
        self.observations = tuple(observations)

    def variant_metrics(self, metric: str) -> dict[str, VariantMetrics]:
        grouped: dict[str, list[OnlineValue]] = {}
        for observation in self.observations:
            if observation.outcome.metric != metric:
                continue
            grouped.setdefault(observation.exposure.variant, []).append(
                observation.outcome.value
            )
        return {
            variant: VariantMetrics(variant, metric, tuple(values))
            for variant, values in sorted(grouped.items())
        }

    def compare(
        self,
        metric: str,
        baseline_variant: str,
        candidate_variant: str,
        confidence: float = 0.95,
        resamples: int = 2000,
        seed: int = 0,
    ) -> OnlineVariantComparison:
        variants = self.variant_metrics(metric)
        if baseline_variant not in variants or candidate_variant not in variants:
            raise ValueError("Both requested variants must have outcome observations.")
        baseline = variants[baseline_variant]
        candidate = variants[candidate_variant]
        ci = bootstrap_difference_ci(
            list(baseline.values),
            list(candidate.values),
            confidence=confidence,
            resamples=resamples,
            seed=seed,
        )
        return OnlineVariantComparison(
            metric=metric,
            baseline_variant=baseline_variant,
            candidate_variant=candidate_variant,
            baseline_sample_size=baseline.sample_size,
            candidate_sample_size=candidate.sample_size,
            baseline_mean=baseline.mean,
            candidate_mean=candidate.mean,
            mean_difference=ci.estimate,
            confidence_interval=ci,
        )


@dataclass(frozen=True)
class OnlineMetricContract:
    experiment_id: str
    metric: str
    exposure_count: int
    outcome_count: int

    def __post_init__(self) -> None:
        if not self.experiment_id.strip() or not self.metric.strip():
            raise ValueError("Experiment id and metric must not be empty.")
        if self.exposure_count < 0 or self.outcome_count < 0:
            raise ValueError("Counts must be non-negative.")


def build_metric_contract(
    exposures: list[Exposure],
    outcomes: list[Outcome],
    metric: str,
) -> OnlineMetricContract:
    if not exposures and not outcomes:
        raise ValueError("At least one exposure or outcome is required.")
    experiment_ids = {item.experiment_id for item in exposures}
    experiment_ids.update(item.experiment_id for item in outcomes)
    if len(experiment_ids) != 1:
        raise ValueError("All observations must belong to one experiment.")
    return OnlineMetricContract(
        experiment_id=next(iter(experiment_ids)),
        metric=metric,
        exposure_count=len(exposures),
        outcome_count=len(outcomes),
    )
