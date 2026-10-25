import math

import pytest

from ai_eval_engineering.tradeoffs import (
    TradeoffObservation,
    quality_cost_frontier,
    quality_latency_frontier,
)


def test_cost_frontier_removes_dominated_variants() -> None:
    observations = [
        TradeoffObservation("cheap", 0.80, 0.01, 100),
        TradeoffObservation("balanced", 0.90, 0.03, 150),
        TradeoffObservation("dominated", 0.85, 0.04, 200),
    ]
    assert {item.variant for item in quality_cost_frontier(observations)} == {
        "cheap",
        "balanced",
    }


def test_latency_frontier_keeps_tradeoffs_instead_of_selecting_one() -> None:
    observations = [
        TradeoffObservation("fast", 0.80, 0.02, 50),
        TradeoffObservation("accurate", 0.95, 0.06, 200),
    ]
    assert {item.variant for item in quality_latency_frontier(observations)} == {
        "fast",
        "accurate",
    }


@pytest.mark.parametrize("field", ["quality", "cost_usd", "latency_ms"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_tradeoff_rejects_non_finite_values(field: str, value: float) -> None:
    fields = {"quality": 0.8, "cost_usd": 0.02, "latency_ms": 100.0}
    fields[field] = value
    with pytest.raises(ValueError, match="finite"):
        TradeoffObservation("variant", **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["quality", "cost_usd", "latency_ms"])
def test_tradeoff_rejects_negative_values(field: str) -> None:
    fields = {"quality": 0.8, "cost_usd": 0.02, "latency_ms": 100.0}
    fields[field] = -1.0
    with pytest.raises(ValueError, match="non-negative"):
        TradeoffObservation("variant", **fields)  # type: ignore[arg-type]


def test_tradeoff_rejects_boolean_numeric_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        TradeoffObservation("variant", True, 0.02, 100.0)  # type: ignore[arg-type]
