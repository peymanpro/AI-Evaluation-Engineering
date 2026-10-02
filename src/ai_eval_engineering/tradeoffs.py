"""Quality/cost/latency observations and non-dominated trade-off views."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradeoffObservation:
    variant: str
    quality: float
    cost_usd: float
    latency_ms: float

    def __post_init__(self) -> None:
        if not self.variant.strip():
            raise ValueError("variant must not be empty")
        if self.quality < 0 or self.cost_usd < 0 or self.latency_ms < 0:
            raise ValueError("quality, cost, and latency must be non-negative")


def quality_cost_frontier(
    observations: list[TradeoffObservation],
) -> tuple[TradeoffObservation, ...]:
    return tuple(
        item
        for item in observations
        if not any(
            other is not item
            and other.quality >= item.quality
            and other.cost_usd <= item.cost_usd
            and (other.quality > item.quality or other.cost_usd < item.cost_usd)
            for other in observations
        )
    )


def quality_latency_frontier(
    observations: list[TradeoffObservation],
) -> tuple[TradeoffObservation, ...]:
    return tuple(
        item
        for item in observations
        if not any(
            other is not item
            and other.quality >= item.quality
            and other.latency_ms <= item.latency_ms
            and (other.quality > item.quality or other.latency_ms < item.latency_ms)
            for other in observations
        )
    )
