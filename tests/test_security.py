import pytest

from ai_eval_engineering.domain import EvaluationCase
from ai_eval_engineering.security import (
    AdversarialCase,
    summarize_adversarial_cases,
    validate_adversarial_case,
)


def make_case(case_id: str, category: str) -> AdversarialCase:
    category_typed = category  # the helper intentionally exercises runtime validation
    case = EvaluationCase(
        case_id,
        {"prompt": "attack"},
        tags=("adversarial", category_typed),
        risk_category=category_typed,
    )
    return AdversarialCase(case, category_typed, "refuse safely")  # type: ignore[arg-type]


def test_adversarial_summary_and_validation() -> None:
    cases = [make_case("a", "prompt_injection"), make_case("b", "tool_abuse")]
    assert summarize_adversarial_cases(cases) == {"prompt_injection": 1, "tool_abuse": 1}
    validate_adversarial_case(cases[0])


def test_adversarial_requires_tag() -> None:
    case = EvaluationCase("x", {}, risk_category="jailbreak")
    wrapped = AdversarialCase(case, "jailbreak", "refuse safely")
    with pytest.raises(ValueError):
        validate_adversarial_case(wrapped)
