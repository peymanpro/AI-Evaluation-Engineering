"""Baseline comparison and deterministic AI behavior release gates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaselineRecord:
    suite_version: str
    system_version: str
    metrics: dict[str, float]


@dataclass(frozen=True)
class RegressionRule:
    metric: str
    max_allowed_drop: float = 0.0


@dataclass(frozen=True)
class GateFailure:
    metric: str
    baseline: float
    current: float
    allowed_drop: float


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: tuple[GateFailure, ...]

    def summary(self) -> str:
        if self.passed:
            return "evaluation gate passed"
        return "; ".join(
            f"{item.metric}: baseline={item.baseline:.4f}, "
            f"current={item.current:.4f}, allowed_drop={item.allowed_drop:.4f}"
            for item in self.failures
        )


def evaluate_gate(
    baseline: BaselineRecord,
    current_metrics: dict[str, float],
    rules: list[RegressionRule],
) -> GateResult:
    failures: list[GateFailure] = []
    for rule in rules:
        if rule.metric not in baseline.metrics:
            raise ValueError(f"Baseline is missing metric {rule.metric!r}.")
        if rule.metric not in current_metrics:
            raise ValueError(f"Current result is missing metric {rule.metric!r}.")
        baseline_value = baseline.metrics[rule.metric]
        current_value = current_metrics[rule.metric]
        if current_value < baseline_value - rule.max_allowed_drop:
            failures.append(GateFailure(rule.metric, baseline_value, current_value, rule.max_allowed_drop))
    return GateResult(passed=not failures, failures=tuple(failures))
