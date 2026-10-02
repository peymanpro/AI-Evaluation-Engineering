"""Demonstrate the vendor-neutral online evaluation layer."""
from __future__ import annotations

import json

from ai_eval_engineering.evidence_guardrails import assess_online_evidence
from ai_eval_engineering.online import ABResultAdapter, Exposure, OnlineObservation, Outcome


def main() -> None:
    observations = [
        OnlineObservation(
            Exposure("checkout-1", "u-1", "control", "mobile"),
            Outcome("checkout-1", "u-1", "conversion", 0.0),
        ),
        OnlineObservation(
            Exposure("checkout-1", "u-2", "control", "desktop"),
            Outcome("checkout-1", "u-2", "conversion", 0.0),
        ),
        OnlineObservation(
            Exposure("checkout-1", "u-3", "treatment", "mobile"),
            Outcome("checkout-1", "u-3", "conversion", 1.0),
        ),
        OnlineObservation(
            Exposure("checkout-1", "u-4", "treatment", "desktop"),
            Outcome("checkout-1", "u-4", "conversion", 1.0),
        ),
    ]

    adapter = ABResultAdapter(observations)
    overall = adapter.compare(
        "conversion", "control", "treatment", resamples=500, seed=11
    )
    segments = adapter.segment_comparisons(
        "conversion", "control", "treatment", resamples=500, seed=11
    )
    evidence = assess_online_evidence(
        [item.exposure for item in observations],
        [item.outcome for item in observations],
        "conversion",
        min_sample_size=3,
    )

    print(
        json.dumps(
            {
                "overall_difference": overall.mean_difference,
                "confidence_interval": {
                    "lower": overall.confidence_interval.lower,
                    "upper": overall.confidence_interval.upper,
                },
                "segments": {
                    segment: comparison.mean_difference
                    for segment, comparison in segments.items()
                },
                "evidence_state": evidence.state,
                "evidence_issues": [issue.code for issue in evidence.issues],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
