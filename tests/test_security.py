import pytest

from ai_eval_engineering.domain import EvaluationCase
from ai_eval_engineering.security import (
    AdversarialCase,
    AdversarialCategory,
    summarize_adversarial_cases,
    validate_adversarial_case,
)


def make_case(case_id: str, category: AdversarialCategory) -> AdversarialCase:
    case = EvaluationCase(
        case_id,
        {"prompt": "attack"},
        tags=("adversarial", category),
        risk_category=category,
    )
    return AdversarialCase(case, category, "refuse safely")


def test_adversarial_summary_and_validation() -> None:
    cases = [
        make_case("a", "prompt_injection"),
        make_case("b", "tool_abuse"),
    ]
    assert summarize_adversarial_cases(cases) == {
        "prompt_injection": 1,
        "tool_abuse": 1,
    }
    validate_adversarial_case(cases[0])


def test_adversarial_requires_the_adversarial_tag() -> None:
    case = EvaluationCase("x", {}, risk_category="jailbreak")
    with pytest.raises(ValueError, match="adversarial"):
        AdversarialCase(case, "jailbreak", "refuse safely")
