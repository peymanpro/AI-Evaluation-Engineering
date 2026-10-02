"""Guardrails for deciding whether online evidence is sufficient to interpret."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .online import Exposure, Outcome

EvidenceIssueCode = Literal[
    "insufficient_sample",
    "overlapping_population",
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
    state: Literal["sufficient", "insufficient"]
    sample_sizes: dict[str, int]
    issues: tuple[EvidenceIssue, ...]

    @property
    def sufficient(self) -> bool:
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
    if min_sample_size < 1:
        raise ValueError("min_sample_size must be at least 1.")
    experiments = {item.experiment_id for item in exposures}
    experiments.update(item.experiment_id for item in outcomes)
    if len(experiments) != 1:
        raise ValueError("All online evidence must belong to one experiment.")

    filtered_outcomes = [item for item in outcomes if item.metric == metric]
    exposure_by_id = {item.exposure_id: item for item in exposures}
    outcome_ids = {item.exposure_id for item in filtered_outcomes}

    sample_sizes: dict[str, int] = {}
    for outcome in filtered_outcomes:
        exposure = exposure_by_id.get(outcome.exposure_id)
        if exposure is not None:
            sample_sizes[exposure.variant] = sample_sizes.get(exposure.variant, 0) + 1

    issues: list[EvidenceIssue] = []
    small_variants = sorted(
        variant for variant, size in sample_sizes.items() if size < min_sample_size
    )
    if small_variants:
        issues.append(
            EvidenceIssue(
                "insufficient_sample",
                f"variants below minimum sample size: {', '.join(small_variants)}",
            )
        )

    variants_by_exposure: dict[str, set[str]] = {}
    for exposure in exposures:
        variants_by_exposure.setdefault(exposure.exposure_id, set()).add(exposure.variant)
    overlapping = sorted(
        exposure_id
        for exposure_id, variants in variants_by_exposure.items()
        if len(variants) > 1
    )
    if overlapping:
        issues.append(
            EvidenceIssue(
                "overlapping_population",
                f"exposure ids assigned to multiple variants: {', '.join(overlapping)}",
            )
        )

    missing_outcomes = sorted(
        exposure.exposure_id
        for exposure in exposures
        if exposure.exposure_id not in outcome_ids
    )
    if missing_outcomes:
        issues.append(
            EvidenceIssue(
                "missing_outcome",
                f"exposures without {metric!r} outcomes: {', '.join(missing_outcomes)}",
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
