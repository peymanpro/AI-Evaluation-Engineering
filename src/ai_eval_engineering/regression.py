"""Baseline comparison and deterministic AI behavior release gates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

MetricDirection = Literal["higher_is_better", "lower_is_better"]


@dataclass(frozen=True)
class BaselineRecord:
    suite_version: str
    system_version: str
    metrics: dict[str, float]

    def __post_init__(self) -> None:
        if not self.suite_version.strip():
            raise ValueError("suite_version must not be empty.")
        if not self.system_version.strip():
            raise ValueError("system_version must not be empty.")
        _validate_metrics(self.metrics, source="baseline")


@dataclass(frozen=True)
class RegressionRule:
    """A metric guardrail.

    `max_allowed_drop` is retained for API compatibility. It represents the
    maximum tolerated regression in the unfavorable direction: a decrease for
    higher-is-better metrics, or an increase for lower-is-better metrics.
    """

    metric: str
    max_allowed_drop: float = 0.0
    direction: MetricDirection = "higher_is_better"

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("metric must not be empty.")
        if (
            isinstance(self.max_allowed_drop, bool)
            or not isinstance(self.max_allowed_drop, (int, float))
            or not math.isfinite(float(self.max_allowed_drop))
        ):
            raise ValueError("max_allowed_drop must be a finite number.")
        if self.max_allowed_drop < 0:
            raise ValueError("max_allowed_drop must be non-negative.")
        if self.direction not in {"higher_is_better", "lower_is_better"}:
            raise ValueError(
                "direction must be 'higher_is_better' or 'lower_is_better'."
            )


@dataclass(frozen=True)
class GateFailure:
    metric: str
    baseline: float
    current: float
    allowed_drop: float
    direction: MetricDirection = "higher_is_better"


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: tuple[GateFailure, ...]

    def summary(self) -> str:
        if self.passed:
            return "evaluation gate passed"
        return "; ".join(
            f"{item.metric}: direction={item.direction}, "
            f"baseline={item.baseline:.4f}, current={item.current:.4f}, "
            f"allowed_regression={item.allowed_drop:.4f}"
            for item in self.failures
        )


def evaluate_gate(
    baseline: BaselineRecord,
    current_metrics: dict[str, float],
    rules: list[RegressionRule],
) -> GateResult:
    """Evaluate metric guardrails with explicit metric direction.

    A rule passes when the current value stays within its allowed regression
    tolerance. Values must be finite so NaN/Infinity cannot silently affect a
    release decision. Suite identity remains caller-managed in this legacy
    function; the decision-grade release API will carry it explicitly.
    """
    _validate_metrics(current_metrics, source="current")

    failures: list[GateFailure] = []
    for rule in rules:
        if rule.metric not in baseline.metrics:
            raise ValueError(f"Baseline is missing metric {rule.metric!r}.")
        if rule.metric not in current_metrics:
            raise ValueError(f"Current result is missing metric {rule.metric!r}.")

        baseline_value = float(baseline.metrics[rule.metric])
        current_value = float(current_metrics[rule.metric])
        tolerance = float(rule.max_allowed_drop)

        if rule.direction == "higher_is_better":
            regressed = current_value < baseline_value - tolerance
        else:
            regressed = current_value > baseline_value + tolerance

        if regressed:
            failures.append(
                GateFailure(
                    metric=rule.metric,
                    baseline=baseline_value,
                    current=current_value,
                    allowed_drop=tolerance,
                    direction=rule.direction,
                )
            )

    return GateResult(passed=not failures, failures=tuple(failures))


def _validate_metrics(metrics: dict[str, float], *, source: str) -> None:
    for name, value in metrics.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{source} metric names must not be empty.")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"{source} metric {name!r} must be a finite number.")
