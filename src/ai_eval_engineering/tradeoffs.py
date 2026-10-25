"""Quality/cost/latency observations and non-dominated trade-off views."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TradeoffObservation:
    variant: str
    quality: float
    cost_usd: float
    latency_ms: float

    def __post_init__(self) -> None:
        if not isinstance(self.variant, str) or not self.variant.strip():
            raise ValueError("variant must not be empty")
        for name, value in (
            ("quality", self.quality),
            ("cost_usd", self.cost_usd),
            ("latency_ms", self.latency_ms),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            try:
                finite_value = float(value)
            except OverflowError as exc:
                raise ValueError(f"{name} must be a finite number") from exc
            if not math.isfinite(finite_value):
                raise ValueError(f"{name} must be a finite number")
            if finite_value < 0:
                raise ValueError(f"{name} must be non-negative")


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
