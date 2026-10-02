"""Show how the framework exposes quality/cost/latency trade-offs."""
from ai_eval_engineering.tradeoffs import (
    TradeoffObservation,
    quality_cost_frontier,
    quality_latency_frontier,
)


def main() -> None:
    observations = [
        TradeoffObservation("variant-a", 0.82, 0.01, 80.0),
        TradeoffObservation("variant-b", 0.91, 0.03, 150.0),
        TradeoffObservation("variant-c", 0.93, 0.06, 260.0),
    ]
    print("Quality/cost frontier:", [item.variant for item in quality_cost_frontier(observations)])
    print(
        "Quality/latency frontier:",
        [item.variant for item in quality_latency_frontier(observations)],
    )
    print("Fixture values are illustrative; they are not production benchmark claims.")


if __name__ == "__main__":
    main()
