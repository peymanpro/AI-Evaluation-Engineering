"""Guardrails for configured online-evidence checks.

A passing assessment means the supplied data passed these explicit checks. It
does not, by itself, establish statistical power, causal validity, or that an
observed effect is practically meaningful.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .online import Exposure, Outcome

EvidenceIssueCode = Literal[
    "insufficient_sample",
    "overlapping_population",
    "duplicate_exposure",
    "duplicate_outcome",
    "unmatched_outcome",
    "missing_exposure",
    "missing_outcome",
    "missing_ground_truth",
    "selection_bias",
]


@dataclass(frozen=True)
class EvidenceIssue:
    code: EvidenceIssueCode
    detail: str


@dataclass(frozen=True)
class EvidenceAssessment:
    """Result of the configured checks, not a universal guarantee of sufficiency."""

    state: Literal["sufficient", "insufficient"]
    sample_sizes: dict[str, int]
    issues: tuple[EvidenceIssue, ...]

    @property
    def sufficient(self) -> bool:
        """Whether configured guardrails passed; not a statistical-power claim."""
        return self.state == "sufficient"


def assess_online_evidence(
    exposures: list[Exposure],
    outcomes: list[Outcome],
    metric: str,
    *,
    min_sample_size: int = 30,
    require_ground_truth: bool = False,
    ground_truth_available: bool = False,
    selection_bias_detected: bool = False,
) -> EvidenceAssessment:
    """Assess data integrity and configured minimums for one experiment/metric.

    Duplicate or unmatched records are reported as evidence issues instead of
    silently inflating counts or disappearing from the assessment. Passing the
    configured minimum is not a substitute for a power analysis or a suitable
    statistical comparison.
    """
    if not isinstance(metric, str) or not metric.strip():
        raise ValueError("metric must not be empty.")
    if (
        isinstance(min_sample_size, bool)
        or not isinstance(min_sample_size, int)
        or min_sample_size < 1
    ):
        raise ValueError("min_sample_size must be a positive integer.")

    experiments = {item.experiment_id for item in exposures}
    experiments.update(item.experiment_id for item in outcomes)
    if len(experiments) != 1:
        raise ValueError("All evidence must belong to exactly one experiment.")

    exposures_by_id: dict[str, list[Exposure]] = {}
    for exposure in exposures:
        exposures_by_id.setdefault(exposure.exposure_id, []).append(exposure)

    issues: list[EvidenceIssue] = []
    exposure_by_id: dict[str, Exposure] = {}
    if not exposures:
        issues.append(
            EvidenceIssue(
                "missing_exposure",
                "no exposure records were supplied for this experiment.",
            )
        )
    duplicate_exposure_ids: list[str] = []
    overlapping_ids: list[str] = []

    for exposure_id, records in sorted(exposures_by_id.items()):
        exposure_by_id[exposure_id] = records[0]
        variants = {record.variant for record in records}
        if len(variants) > 1:
            overlapping_ids.append(exposure_id)
        elif len(records) > 1:
            duplicate_exposure_ids.append(exposure_id)

    if overlapping_ids:
        issues.append(
            EvidenceIssue(
                "overlapping_population",
                "exposure ids assigned to multiple variants: "
                + ", ".join(overlapping_ids),
            )
        )
    if duplicate_exposure_ids:
        issues.append(
            EvidenceIssue(
                "duplicate_exposure",
                "exposure ids occur more than once: "
                + ", ".join(duplicate_exposure_ids),
            )
        )

    metric_outcomes: dict[str, list[Outcome]] = {}
    for outcome in outcomes:
        if outcome.metric == metric:
            metric_outcomes.setdefault(outcome.exposure_id, []).append(outcome)

    duplicate_outcome_ids = sorted(
        exposure_id
        for exposure_id, records in metric_outcomes.items()
        if len(records) > 1
    )
    if duplicate_outcome_ids:
        issues.append(
            EvidenceIssue(
                "duplicate_outcome",
                f"multiple {metric!r} outcomes for exposure ids: "
                + ", ".join(duplicate_outcome_ids),
            )
        )

    unique_outcomes = [
        records[0] for _, records in sorted(metric_outcomes.items())
    ]
    unmatched_outcome_ids = sorted(
        outcome.exposure_id
        for outcome in unique_outcomes
        if outcome.exposure_id not in exposure_by_id
    )
    if unmatched_outcome_ids:
        issues.append(
            EvidenceIssue(
                "unmatched_outcome",
                "outcomes reference unknown exposure ids: "
                + ", ".join(unmatched_outcome_ids),
            )
        )

    # Count each known exposure at most once. Start all observed variants at
    # zero, so an arm with no usable outcomes cannot vanish from sample checks.
    sample_sizes: dict[str, int] = {}
    for exposure in exposure_by_id.values():
        sample_sizes.setdefault(exposure.variant, 0)

    outcome_ids: set[str] = set()
    for outcome in unique_outcomes:
        exposure = exposure_by_id.get(outcome.exposure_id)
        if exposure is not None:
            sample_sizes[exposure.variant] += 1
            outcome_ids.add(outcome.exposure_id)

    small_variants = sorted(
        variant for variant, size in sample_sizes.items() if size < min_sample_size
    )
    if small_variants:
        details = ", ".join(
            f"{variant} (n={sample_sizes[variant]})" for variant in small_variants
        )
        issues.append(
            EvidenceIssue(
                "insufficient_sample",
                f"variants below configured minimum n={min_sample_size}: {details}",
            )
        )

    missing_outcomes = sorted(
        exposure_id
        for exposure_id in exposure_by_id
        if exposure_id not in outcome_ids
    )
    if missing_outcomes:
        issues.append(
            EvidenceIssue(
                "missing_outcome",
                f"exposures without {metric!r} outcomes: " + ", ".join(missing_outcomes),
            )
        )

    if require_ground_truth and not ground_truth_available:
        issues.append(
            EvidenceIssue(
                "missing_ground_truth",
                "ground truth is required by policy but was not supplied.",
            )
        )

    if selection_bias_detected:
        issues.append(
            EvidenceIssue(
                "selection_bias",
                "selection bias was flagged in the sampling or exposure process.",
            )
        )

    return EvidenceAssessment(
        state="insufficient" if issues else "sufficient",
        sample_sizes=dict(sorted(sample_sizes.items())),
        issues=tuple(issues),
    )
