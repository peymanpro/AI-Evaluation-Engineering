"""Small, explicit taxonomy for AI security evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .domain import EvaluationCase

AdversarialCategory = Literal[
    "prompt_injection",
    "jailbreak",
    "tool_abuse",
    "data_leakage",
    "permission_violation",
    "unsafe_side_effect",
]


@dataclass(frozen=True)
class AdversarialCase:
    case: EvaluationCase
    category: AdversarialCategory
    expected_behavior: str

    def __post_init__(self) -> None:
        if self.case.risk_category != self.category:
            raise ValueError(
                f"Evaluation case risk_category must match category {self.category!r}."
            )
        if "adversarial" not in self.case.tags:
            raise ValueError("Adversarial cases must include the 'adversarial' tag.")
        if not self.expected_behavior.strip():
            raise ValueError("Expected adversarial behavior must not be empty.")


def validate_adversarial_case(case: AdversarialCase) -> None:
    case.__post_init__()


def summarize_adversarial_cases(cases: list[AdversarialCase]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for case in cases:
        validate_adversarial_case(case)
        summary[case.category] = summary.get(case.category, 0) + 1
    return dict(sorted(summary.items()))
