"""Decision-grade, paired release evaluation for AI system runs.

The release decision is deterministic given the two recorded runs, policy, and
bootstrap seed. A PASS means the configured paired-bootstrap interval stays
within each metric's allowed regression tolerance on the evaluated cases; it
is not a guarantee of production-wide quality.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from typing import Literal

from .domain import CaseResult, EvaluationRun, GraderResult
from .regression import MetricDirection
from .statistics import ConfidenceInterval, paired_bootstrap_difference_ci

ReleaseStatus = Literal["PASS", "FAIL", "INCONCLUSIVE", "INVALID_EVIDENCE"]
MetricStatus = Literal["PASS", "FAIL", "INCONCLUSIVE"]


@dataclass(frozen=True)
class ReleaseMetricPolicy:
    """Release rule for one numeric grader metric.

    `max_allowed_regression` is expressed in the metric's natural units.
    For higher-is-better metrics, it tolerates a decrease; for lower-is-better
    metrics, it tolerates an increase.
    """

    metric: str
    direction: MetricDirection = "higher_is_better"
    max_allowed_regression: float = 0.0
    min_cases: int = 30

    def __post_init__(self) -> None:
        if not isinstance(self.metric, str) or not self.metric.strip():
            raise ValueError("metric must not be empty.")
        if self.direction not in {"higher_is_better", "lower_is_better"}:
            raise ValueError(
                "direction must be 'higher_is_better' or 'lower_is_better'."
            )
        if (
            isinstance(self.max_allowed_regression, bool)
            or not isinstance(self.max_allowed_regression, (int, float))
        ):
            raise TypeError("max_allowed_regression must be numeric.")
        if not math.isfinite(float(self.max_allowed_regression)):
            raise ValueError("max_allowed_regression must be finite.")
        if self.max_allowed_regression < 0:
            raise ValueError("max_allowed_regression must be non-negative.")
        if isinstance(self.min_cases, bool) or not isinstance(self.min_cases, int):
            raise TypeError("min_cases must be an integer.")
        if self.min_cases < 2:
            raise ValueError("min_cases must be at least 2.")


@dataclass(frozen=True)
class MetricGateDecision:
    metric: str
    direction: MetricDirection
    baseline_mean: float
    candidate_mean: float
    observed_difference: float
    favorable_difference: float
    confidence_interval: ConfidenceInterval | None
    favorable_interval: tuple[float, float] | None
    sample_size: int
    status: MetricStatus
    reason: str


@dataclass(frozen=True)
class ReleaseGateDecision:
    status: ReleaseStatus
    baseline_system_version: str | None
    candidate_system_version: str | None
    suite_version: str | None
    metrics: tuple[MetricGateDecision, ...]
    reasons: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """True only when all configured metric gates pass."""
        return self.status == "PASS"

    def summary(self) -> str:
        if self.status == "PASS":
            return "release gate passed: all configured metrics are within tolerance"
        prefix = f"release gate {self.status.lower()}"
        return prefix if not self.reasons else f"{prefix}: " + "; ".join(self.reasons)


def evaluate_release_candidate(
    baseline: EvaluationRun,
    candidate: EvaluationRun,
    policies: list[ReleaseMetricPolicy],
    *,
    confidence: float = 0.95,
    resamples: int = 2000,
    seed: int = 0,
) -> ReleaseGateDecision:
    """Compare candidate to baseline on identical, paired evaluation cases.

    Invalid or unmatched evidence returns `INVALID_EVIDENCE`; a small sample
    returns `INCONCLUSIVE` without a confidence interval. No external model
    calls are made in the release-decision path.
    """
    _validate_options(confidence=confidence, resamples=resamples, seed=seed)
    if not policies:
        raise ValueError("At least one metric policy is required.")
    policy_names = [policy.metric for policy in policies]
    if len(policy_names) != len(set(policy_names)):
        raise ValueError("Metric policies must not contain duplicate metric names.")

    invalid_reasons = _validate_runs(baseline, candidate)
    if invalid_reasons:
        return ReleaseGateDecision(
            status="INVALID_EVIDENCE",
            baseline_system_version=_system_version(baseline),
            candidate_system_version=_system_version(candidate),
            suite_version=_suite_version(baseline),
            metrics=(),
            reasons=tuple(invalid_reasons),
        )

    baseline_by_id = {result.case.id: result for result in baseline.cases}
    candidate_by_id = {result.case.id: result for result in candidate.cases}
    case_ids = sorted(baseline_by_id)

    for case_id in case_ids:
        if _case_signature(baseline_by_id[case_id]) != _case_signature(
            candidate_by_id[case_id]
        ):
            return _invalid(
                baseline, candidate, f"case definition changed for case {case_id!r}."
            )

    decisions: list[MetricGateDecision] = []
    for policy in policies:
        baseline_scores, baseline_error = _metric_scores(
            baseline_by_id, case_ids, policy.metric, "baseline"
        )
        candidate_scores, candidate_error = _metric_scores(
            candidate_by_id, case_ids, policy.metric, "candidate"
        )
        if baseline_error or candidate_error:
            reasons = tuple(item for item in (baseline_error, candidate_error) if item)
            return ReleaseGateDecision(
                status="INVALID_EVIDENCE",
                baseline_system_version=baseline.manifest.system_version,
                candidate_system_version=candidate.manifest.system_version,
                suite_version=baseline.manifest.suite_version,
                metrics=tuple(decisions),
                reasons=reasons,
            )

        assert baseline_scores is not None and candidate_scores is not None
        sample_size = len(case_ids)
        baseline_mean = statistics.fmean(baseline_scores)
        candidate_mean = statistics.fmean(candidate_scores)
        observed_difference = candidate_mean - baseline_mean
        favorable_difference = (
            observed_difference
            if policy.direction == "higher_is_better"
            else -observed_difference
        )

        if sample_size < policy.min_cases:
            decisions.append(
                MetricGateDecision(
                    metric=policy.metric,
                    direction=policy.direction,
                    baseline_mean=baseline_mean,
                    candidate_mean=candidate_mean,
                    observed_difference=observed_difference,
                    favorable_difference=favorable_difference,
                    confidence_interval=None,
                    favorable_interval=None,
                    sample_size=sample_size,
                    status="INCONCLUSIVE",
                    reason=(
                        f"only {sample_size} matched cases; "
                        f"at least {policy.min_cases} are required by policy"
                    ),
                )
            )
            continue

        interval = paired_bootstrap_difference_ci(
            baseline_scores,
            candidate_scores,
            confidence=confidence,
            resamples=resamples,
            seed=seed,
        )
        if policy.direction == "higher_is_better":
            favorable_interval = (interval.lower, interval.upper)
        else:
            favorable_interval = (-interval.upper, -interval.lower)

        threshold = -float(policy.max_allowed_regression)
        lower, upper = favorable_interval
        if lower >= threshold:
            status: MetricStatus = "PASS"
            reason = (
                f"{confidence:.1%} paired-bootstrap interval lower bound "
                f"{lower:.6g} meets allowed-regression threshold {threshold:.6g}"
            )
        elif upper < threshold:
            status = "FAIL"
            reason = (
                f"{confidence:.1%} paired-bootstrap interval upper bound "
                f"{upper:.6g} is below allowed-regression threshold {threshold:.6g}"
            )
        else:
            status = "INCONCLUSIVE"
            reason = (
                f"{confidence:.1%} paired-bootstrap interval "
                f"[{lower:.6g}, {upper:.6g}] overlaps allowed-regression "
                f"threshold {threshold:.6g}"
            )

        decisions.append(
            MetricGateDecision(
                metric=policy.metric,
                direction=policy.direction,
                baseline_mean=baseline_mean,
                candidate_mean=candidate_mean,
                observed_difference=observed_difference,
                favorable_difference=favorable_difference,
                confidence_interval=interval,
                favorable_interval=favorable_interval,
                sample_size=sample_size,
                status=status,
                reason=reason,
            )
        )

    if any(item.status == "FAIL" for item in decisions):
        status: ReleaseStatus = "FAIL"
    elif any(item.status == "INCONCLUSIVE" for item in decisions):
        status = "INCONCLUSIVE"
    else:
        status = "PASS"

    reasons = tuple(
        f"{item.metric}: {item.reason}"
        for item in decisions
        if item.status != "PASS"
    )
    return ReleaseGateDecision(
        status=status,
        baseline_system_version=baseline.manifest.system_version,
        candidate_system_version=candidate.manifest.system_version,
        suite_version=baseline.manifest.suite_version,
        metrics=tuple(decisions),
        reasons=reasons,
    )


def _validate_runs(
    baseline: EvaluationRun, candidate: EvaluationRun
) -> list[str]:
    reasons: list[str] = []
    for label, run in (("baseline", baseline), ("candidate", candidate)):
        manifest = run.manifest
        for field_name in ("suite_version", "system_name", "system_version"):
            value = getattr(manifest, field_name)
            if not isinstance(value, str) or not value.strip():
                reasons.append(f"{label} manifest has empty {field_name}.")
        if not run.cases:
            reasons.append(f"{label} run contains no cases.")

    if reasons:
        return reasons
    if baseline.manifest.suite_version != candidate.manifest.suite_version:
        reasons.append(
            "baseline and candidate use different suite versions "
            f"({baseline.manifest.suite_version!r} vs "
            f"{candidate.manifest.suite_version!r})."
        )
    if baseline.manifest.system_name != candidate.manifest.system_name:
        reasons.append(
            "baseline and candidate system names differ "
            f"({baseline.manifest.system_name!r} vs "
            f"{candidate.manifest.system_name!r})."
        )

    baseline_ids = _case_ids(baseline, "baseline", reasons)
    candidate_ids = _case_ids(candidate, "candidate", reasons)
    if baseline_ids is not None and candidate_ids is not None:
        if baseline_ids != candidate_ids:
            missing_candidate = sorted(baseline_ids - candidate_ids)
            missing_baseline = sorted(candidate_ids - baseline_ids)
            if missing_candidate:
                reasons.append(
                    "candidate is missing case ids: " + ", ".join(missing_candidate)
                )
            if missing_baseline:
                reasons.append(
                    "candidate contains unmatched case ids: "
                    + ", ".join(missing_baseline)
                )

    return reasons


def _case_ids(run: EvaluationRun, label: str, reasons: list[str]) -> set[str] | None:
    ids: list[str] = []
    for result in run.cases:
        case_id = result.case.id
        if not isinstance(case_id, str) or not case_id.strip():
            reasons.append(f"{label} run contains an empty or invalid case id.")
            continue
        ids.append(case_id)
        if result.output.case_id != case_id:
            reasons.append(
                f"{label} output case id {result.output.case_id!r} "
                f"does not match case id {case_id!r}."
            )
        try:
            _case_signature(result)
        except (TypeError, ValueError) as exc:
            reasons.append(f"{label} case {case_id!r} is not JSON-serializable: {exc}.")
        names = [grader.grader for grader in result.graders]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            reasons.append(f"{label} case {case_id!r} contains an empty grader name.")
        if len(names) != len(set(names)):
            reasons.append(f"{label} case {case_id!r} contains duplicate grader names.")
        for grader in result.graders:
            if (
                isinstance(grader.score, bool)
                or not isinstance(grader.score, (int, float))
            ):
                reasons.append(
                    f"{label} case {case_id!r} grader {grader.grader!r} "
                    "has a non-numeric score."
                )
            elif not math.isfinite(float(grader.score)):
                reasons.append(
                    f"{label} case {case_id!r} grader {grader.grader!r} "
                    "has a non-finite score."
                )
    if len(ids) != len(set(ids)):
        reasons.append(f"{label} run contains duplicate case ids.")
    return set(ids) if len(ids) == len(set(ids)) else None


def _case_signature(result: CaseResult) -> str:
    case = result.case
    return json.dumps(
        {
            "id": case.id,
            "input": case.input,
            "expected": case.expected,
            "metadata": case.metadata,
            "tags": case.tags,
            "risk_category": case.risk_category,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _metric_scores(
    by_id: dict[str, CaseResult],
    case_ids: list[str],
    metric: str,
    label: str,
) -> tuple[list[float] | None, str | None]:
    scores: list[float] = []
    for case_id in case_ids:
        result = by_id[case_id]
        matches = [grader for grader in result.graders if grader.grader == metric]
        if not matches:
            return None, f"{label} run is missing grader metric {metric!r} for case {case_id!r}."
        if len(matches) != 1:
            return None, f"{label} run has duplicate grader metric {metric!r} for case {case_id!r}."
        score = matches[0].score
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            return None, f"{label} run has invalid score for metric {metric!r}, case {case_id!r}."
        scores.append(float(score))
    return scores, None


def _validate_options(*, confidence: float, resamples: int, seed: int) -> None:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("confidence must be numeric.")
    if not math.isfinite(float(confidence)) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be finite and between 0 and 1.")
    if isinstance(resamples, bool) or not isinstance(resamples, int):
        raise TypeError("resamples must be an integer.")
    if resamples < 100:
        raise ValueError("resamples must be at least 100.")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer.")


def _invalid(
    baseline: EvaluationRun, candidate: EvaluationRun, reason: str
) -> ReleaseGateDecision:
    return ReleaseGateDecision(
        status="INVALID_EVIDENCE",
        baseline_system_version=_system_version(baseline),
        candidate_system_version=_system_version(candidate),
        suite_version=_suite_version(baseline),
        metrics=(),
        reasons=(reason,),
    )


def _system_version(run: EvaluationRun) -> str | None:
    value = getattr(run.manifest, "system_version", None)
    return value if isinstance(value, str) else None


def _suite_version(run: EvaluationRun) -> str | None:
    value = getattr(run.manifest, "suite_version", None)
    return value if isinstance(value, str) else None
