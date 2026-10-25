import math

import pytest

from ai_eval_engineering.regression import (
    BaselineRecord,
    RegressionRule,
    evaluate_gate,
)


def test_gate_passes_within_allowed_drop() -> None:
    baseline = BaselineRecord("suite-1", "model-a", {"accuracy": 0.9})
    result = evaluate_gate(
        baseline,
        {"accuracy": 0.89},
        [RegressionRule("accuracy", 0.02)],
    )
    assert result.passed


def test_gate_fails_on_regression() -> None:
    baseline = BaselineRecord("suite-1", "model-a", {"accuracy": 0.9})
    result = evaluate_gate(
        baseline,
        {"accuracy": 0.85},
        [RegressionRule("accuracy", 0.02)],
    )
    assert not result.passed
    assert result.failures[0].metric == "accuracy"
    assert result.failures[0].direction == "higher_is_better"


def test_lower_is_better_metric_passes_when_value_improves() -> None:
    baseline = BaselineRecord("suite-1", "model-a", {"latency_ms": 200.0})
    result = evaluate_gate(
        baseline,
        {"latency_ms": 150.0},
        [RegressionRule("latency_ms", direction="lower_is_better")],
    )
    assert result.passed


def test_lower_is_better_metric_fails_when_regression_exceeds_tolerance() -> None:
    baseline = BaselineRecord("suite-1", "model-a", {"cost_usd": 0.01})
    result = evaluate_gate(
        baseline,
        {"cost_usd": 0.013},
        [RegressionRule("cost_usd", 0.002, direction="lower_is_better")],
    )
    assert not result.passed
    assert result.failures[0].baseline == pytest.approx(0.01)
    assert result.failures[0].current == pytest.approx(0.013)
    assert "direction=lower_is_better" in result.summary()


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_gate_rejects_non_finite_current_metrics(value: float) -> None:
    baseline = BaselineRecord("suite-1", "model-a", {"accuracy": 0.9})
    with pytest.raises(ValueError, match="finite number"):
        evaluate_gate(baseline, {"accuracy": value}, [RegressionRule("accuracy")])


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True])
def test_baseline_rejects_invalid_metric_values(value: float | bool) -> None:
    with pytest.raises(ValueError, match="finite number"):
        BaselineRecord("suite-1", "model-a", {"accuracy": value})  # type: ignore[dict-item]


@pytest.mark.parametrize("tolerance", [-0.01, math.nan, math.inf, -math.inf, True])
def test_regression_rule_rejects_invalid_tolerance(tolerance: float | bool) -> None:
    with pytest.raises(ValueError):
        RegressionRule("accuracy", tolerance)  # type: ignore[arg-type]


def test_regression_rule_rejects_unknown_direction() -> None:
    with pytest.raises(ValueError, match="direction"):
        RegressionRule("accuracy", direction="neutral")  # type: ignore[arg-type]
