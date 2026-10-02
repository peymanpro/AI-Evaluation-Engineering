from ai_eval_engineering.tradeoffs import (
    TradeoffObservation,
    quality_cost_frontier,
    quality_latency_frontier,
)


def test_cost_frontier_preserves_non_dominated_variants() -> None:
    observations = [
        TradeoffObservation("cheap", 0.80, 0.01, 100),
        TradeoffObservation("balanced", 0.90, 0.03, 150),
        TradeoffObservation("dominated", 0.85, 0.04, 200),
    ]
    assert {item.variant for item in quality_cost_frontier(observations)} == {"cheap", "balanced"}


def test_latency_frontier_does_not_select_a_single_winner() -> None:
    observations = [
        TradeoffObservation("fast", 0.80, 0.02, 50),
        TradeoffObservation("accurate", 0.95, 0.06, 200),
    ]
    assert {item.variant for item in quality_latency_frontier(observations)} == {"fast", "accurate"}
