"""Post-run cost, token, and latency budget assessment."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from .domain import CaseResult, EvaluationCase, EvaluationRun, GraderResult, RunMetadata, SystemOutput

BudgetStatus = Literal[
    "WITHIN_BUDGET",
    "BUDGET_EXCEEDED",
    "INCOMPLETE_EVIDENCE",
    "INVALID_EVIDENCE",
]
BudgetMetric = Literal[
    "total_cost_usd",
    "case_cost_usd",
    "total_tokens",
    "case_latency_ms",
]


@dataclass(frozen=True)
class RunBudgetPolicy:
    """Limits for measurements already recorded in an EvaluationRun.

    Cost is read from each SystemOutput.cost_usd. Token usage is read from
    GraderResult.metadata["usage"], normally populated by model-based graders.
    This assesses a completed run; it does not stop live requests before spend.
    """

    max_total_cost_usd: float | None = None
    max_case_cost_usd: float | None = None
    max_total_tokens: int | None = None
    max_case_latency_ms: float | None = None

    def __post_init__(self) -> None:
        limits = (
            ("max_total_cost_usd", self.max_total_cost_usd),
            ("max_case_cost_usd", self.max_case_cost_usd),
            ("max_case_latency_ms", self.max_case_latency_ms),
        )
        if all(value is None for _, value in limits) and self.max_total_tokens is None:
            raise ValueError("At least one budget limit must be configured.")
        for name, value in limits:
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric or None.")
            try:
                numeric_value = float(value)
            except OverflowError as exc:
                raise ValueError(f"{name} must be finite and non-negative.") from exc
            if not math.isfinite(numeric_value) or numeric_value < 0:
                raise ValueError(f"{name} must be finite and non-negative.")
        if self.max_total_tokens is not None:
            if isinstance(self.max_total_tokens, bool) or not isinstance(
                self.max_total_tokens, int
            ):
                raise TypeError("max_total_tokens must be an integer or None.")
            if self.max_total_tokens < 0:
                raise ValueError("max_total_tokens must be non-negative.")


@dataclass(frozen=True)
class BudgetViolation:
    """A measured budget limit that the run exceeded."""

    metric: BudgetMetric
    observed: float | int
    limit: float | int
    case_id: str | None
    detail: str


@dataclass(frozen=True)
class BudgetAssessment:
    """Budget assessment with missing measurements kept separate from zero."""

    status: BudgetStatus
    total_cost_usd: float | None
    known_cost_subtotal_usd: float
    total_tokens: int | None
    known_token_subtotal: int
    highest_observed_case_cost_usd: float | None
    highest_observed_case_latency_ms: float | None
    missing_cost_case_ids: tuple[str, ...]
    missing_token_case_ids: tuple[str, ...]
    missing_latency_case_ids: tuple[str, ...]
    violations: tuple[BudgetViolation, ...]
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """True only when all configured limits are evidenced and satisfied."""
        return self.status == "WITHIN_BUDGET"


def assess_run_budget(
    run: EvaluationRun,
    policy: RunBudgetPolicy,
) -> BudgetAssessment:
    """Assess recorded cost, token, and latency measurements against limits.

    Missing measurements never count as zero. Known violations take precedence
    over missing measurements, except malformed evidence makes the assessment
    invalid. A total is reported as complete only when every case has a valid
    measurement for that dimension.
    """
    if not isinstance(run, EvaluationRun):
        raise TypeError("run must be an EvaluationRun.")
    if not isinstance(policy, RunBudgetPolicy):
        raise TypeError("policy must be a RunBudgetPolicy.")

    if not run.cases:
        return BudgetAssessment(
            status="INCOMPLETE_EVIDENCE",
            total_cost_usd=None,
            known_cost_subtotal_usd=0.0,
            total_tokens=None,
            known_token_subtotal=0,
            highest_observed_case_cost_usd=None,
            highest_observed_case_latency_ms=None,
            missing_cost_case_ids=(),
            missing_token_case_ids=(),
            missing_latency_case_ids=(),
            violations=(),
            issues=("run contains no cases; budget compliance cannot be established.",),
        )

    issues: list[str] = []
    invalid_evidence = False
    violations: list[BudgetViolation] = []
    missing_cost: list[str] = []
    missing_tokens: list[str] = []
    missing_latency: list[str] = []
    costs: list[float] = []
    latencies: list[float] = []
    token_totals: list[int] = []

    for index, result in enumerate(run.cases):
        if not isinstance(result, CaseResult):
            issues.append(f"cases[{index}] is not a CaseResult.")
            invalid_evidence = True
            continue
        if not isinstance(result.case, EvaluationCase):
            issues.append(f"cases[{index}] does not contain an EvaluationCase.")
            invalid_evidence = True
            continue
        case_id = result.case.id
        if not isinstance(case_id, str) or not case_id.strip():
            issues.append(f"cases[{index}] has an empty or invalid case id.")
            invalid_evidence = True
            case_id = f"<cases[{index}]>"
        output = result.output
        if not isinstance(output, SystemOutput):
            issues.append(f"case {case_id!r} output is not a SystemOutput.")
            invalid_evidence = True
            missing_cost.append(case_id)
            missing_latency.append(case_id)
            missing_tokens.append(case_id)
            continue

        cost = _read_non_negative_measurement(
            output.cost_usd, "cost_usd", case_id, issues
        )
        latency = _read_non_negative_measurement(
            output.latency_ms, "latency_ms", case_id, issues
        )
        if output.cost_usd is None:
            missing_cost.append(case_id)
        elif cost is None:
            invalid_evidence = True
        else:
            costs.append(cost)
            if (
                policy.max_case_cost_usd is not None
                and cost > float(policy.max_case_cost_usd)
            ):
                violations.append(
                    BudgetViolation(
                        metric="case_cost_usd",
                        observed=cost,
                        limit=float(policy.max_case_cost_usd),
                        case_id=case_id,
                        detail=(
                            f"case cost {cost:.8g} USD exceeds per-case limit "
                            f"{policy.max_case_cost_usd:.8g} USD"
                        ),
                    )
                )

        if output.latency_ms is None:
            missing_latency.append(case_id)
        elif latency is None:
            invalid_evidence = True
        else:
            latencies.append(latency)
            if (
                policy.max_case_latency_ms is not None
                and latency > float(policy.max_case_latency_ms)
            ):
                violations.append(
                    BudgetViolation(
                        metric="case_latency_ms",
                        observed=latency,
                        limit=float(policy.max_case_latency_ms),
                        case_id=case_id,
                        detail=(
                            f"case latency {latency:.8g} ms exceeds per-case limit "
                            f"{policy.max_case_latency_ms:.8g} ms"
                        ),
                    )
                )

        case_tokens, token_invalid, token_issue = _read_case_token_usage(result, case_id)
        if token_issue:
            issues.append(token_issue)
        if token_invalid:
            invalid_evidence = True
        if case_tokens is None:
            missing_tokens.append(case_id)
        else:
            token_totals.append(case_tokens)

    known_cost_subtotal = math.fsum(costs)
    known_token_subtotal = sum(token_totals)
    highest_case_cost = max(costs) if costs else None
    highest_case_latency = max(latencies) if latencies else None
    all_costs_present = len(costs) == len(run.cases) and not missing_cost
    all_latencies_present = len(latencies) == len(run.cases) and not missing_latency
    all_tokens_present = len(token_totals) == len(run.cases) and not missing_tokens
    total_cost = known_cost_subtotal if all_costs_present and not invalid_evidence else None
    total_tokens = known_token_subtotal if all_tokens_present and not invalid_evidence else None

    if policy.max_total_cost_usd is not None:
        limit = float(policy.max_total_cost_usd)
        if known_cost_subtotal > limit:
            violations.append(
                BudgetViolation(
                    metric="total_cost_usd",
                    observed=known_cost_subtotal,
                    limit=limit,
                    case_id=None,
                    detail=(
                        f"known cost subtotal {known_cost_subtotal:.8g} USD already exceeds "
                        f"total cost limit {limit:.8g} USD"
                    ),
                )
            )
        elif not all_costs_present:
            issues.append("total cost limit requires a valid cost measurement for every case.")

    if policy.max_total_tokens is not None:
        limit_tokens = policy.max_total_tokens
        if known_token_subtotal > limit_tokens:
            violations.append(
                BudgetViolation(
                    metric="total_tokens",
                    observed=known_token_subtotal,
                    limit=limit_tokens,
                    case_id=None,
                    detail=(
                        f"known token subtotal {known_token_subtotal} already exceeds "
                        f"total token limit {limit_tokens}"
                    ),
                )
            )
        elif not all_tokens_present:
            issues.append("token budget requires valid usage metadata for every case.")

    if policy.max_case_cost_usd is not None and missing_cost:
        issues.append("per-case cost limit cannot be verified for every case.")
    if policy.max_case_latency_ms is not None and not all_latencies_present:
        issues.append("per-case latency limit cannot be verified for every case.")

    if invalid_evidence:
        status: BudgetStatus = "INVALID_EVIDENCE"
    elif violations:
        status = "BUDGET_EXCEEDED"
    elif (
        (policy.max_total_cost_usd is not None or policy.max_case_cost_usd is not None)
        and missing_cost
    ) or (policy.max_total_tokens is not None and not all_tokens_present) or (
        policy.max_case_latency_ms is not None and not all_latencies_present
    ):
        status = "INCOMPLETE_EVIDENCE"
    else:
        status = "WITHIN_BUDGET"

    return BudgetAssessment(
        status=status,
        total_cost_usd=total_cost,
        known_cost_subtotal_usd=known_cost_subtotal,
        total_tokens=total_tokens,
        known_token_subtotal=known_token_subtotal,
        highest_observed_case_cost_usd=highest_case_cost,
        highest_observed_case_latency_ms=highest_case_latency,
        missing_cost_case_ids=tuple(sorted(missing_cost)),
        missing_token_case_ids=tuple(sorted(missing_tokens)),
        missing_latency_case_ids=tuple(sorted(missing_latency)),
        violations=tuple(violations),
        issues=tuple(issues),
    )


def _read_non_negative_measurement(
    value: Any,
    name: str,
    case_id: str,
    issues: list[str],
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append(f"case {case_id!r} {name} must be numeric.")
        return None
    try:
        numeric = float(value)
    except OverflowError:
        numeric = math.inf
    if not math.isfinite(numeric) or numeric < 0:
        issues.append(f"case {case_id!r} {name} must be finite and non-negative.")
        return None
    return numeric


def _read_case_token_usage(
    result: CaseResult,
    case_id: str,
) -> tuple[int | None, bool, str | None]:
    if not isinstance(result.graders, (tuple, list)):
        return None, True, f"case {case_id!r} grader results must be a sequence."
    totals: list[int] = []
    for grader in result.graders:
        if not isinstance(grader, GraderResult):
            return None, True, f"case {case_id!r} contains an invalid GraderResult."
        if not isinstance(grader.metadata, dict):
            return None, True, f"case {case_id!r} grader metadata must be an object."
        if "usage" not in grader.metadata:
            continue
        usage = grader.metadata["usage"]
        if not isinstance(usage, dict):
            return None, True, f"case {case_id!r} grader usage metadata must be an object."

        parsed: dict[str, int] = {}
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if name not in usage:
                continue
            value = usage[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return (
                    None,
                    True,
                    f"case {case_id!r} grader usage field {name!r} must be a non-negative integer.",
                )
            parsed[name] = value

        if "total_tokens" in parsed:
            totals.append(parsed["total_tokens"])
        elif "prompt_tokens" in parsed and "completion_tokens" in parsed:
            totals.append(parsed["prompt_tokens"] + parsed["completion_tokens"])
        else:
            return (
                None,
                False,
                f"case {case_id!r} grader usage must include total_tokens or both prompt and completion counts.",
            )

    return (sum(totals), False, None) if totals else (None, False, None)


LiveBudgetStatus = Literal[
    "COMPLETED",
    "BUDGET_LIMIT_REACHED",
    "INCOMPLETE_BUDGET_EVIDENCE",
    "INVALID_BUDGET_EVIDENCE",
]


@dataclass(frozen=True)
class BudgetedRunResult:
    """Result of a run that may stop before every suite case is executed.

    Partial results deliberately use a distinct type rather than EvaluationRun,
    whose contract represents a completed suite.
    """

    manifest: RunMetadata
    completed_cases: tuple[CaseResult, ...]
    pending_case_ids: tuple[str, ...]
    status: LiveBudgetStatus
    known_cost_usd: float
    known_tokens: int
    stop_reason: str | None

    @property
    def all_cases_completed(self) -> bool:
        """Whether every case in the suite has a recorded CaseResult."""
        return not self.pending_case_ids

    @property
    def within_budget(self) -> bool:
        """True only when the run completed without triggering a live guard."""
        return self.status == "COMPLETED" and self.all_cases_completed


class _LiveBudgetGuard:
    """Track measurements as they become available and gate new case starts."""

    def __init__(self, policy: RunBudgetPolicy) -> None:
        if not isinstance(policy, RunBudgetPolicy):
            raise TypeError("policy must be a RunBudgetPolicy.")
        self.policy = policy
        self._known_cost_usd = 0.0
        self._known_tokens = 0
        self._seen_output_ids: set[str] = set()
        self._seen_usage_ids: set[str] = set()
        self._stop_status: LiveBudgetStatus | None = None
        self._stop_reason: str | None = None

    @property
    def known_cost_usd(self) -> float:
        return self._known_cost_usd

    @property
    def known_tokens(self) -> int:
        return self._known_tokens

    @property
    def stop_status(self) -> LiveBudgetStatus | None:
        return self._stop_status

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def can_start_case(self) -> bool:
        """Return false once a configured limit is reached or evidence is missing."""
        if self._stop_status is not None:
            return False
        if (
            self.policy.max_total_cost_usd is not None
            and self._known_cost_usd >= float(self.policy.max_total_cost_usd)
        ):
            self._stop(
                "BUDGET_LIMIT_REACHED",
                (
                    f"known cumulative cost {self._known_cost_usd:.8g} USD has reached "
                    f"the total cost cap {self.policy.max_total_cost_usd:.8g} USD"
                ),
            )
        if (
            self._stop_status is None
            and self.policy.max_total_tokens is not None
            and self._known_tokens >= self.policy.max_total_tokens
        ):
            self._stop(
                "BUDGET_LIMIT_REACHED",
                (
                    f"known cumulative tokens {self._known_tokens} have reached "
                    f"the total token cap {self.policy.max_total_tokens}"
                ),
            )
        return self._stop_status is None

    def observe_output(self, case_id: str, output: SystemOutput) -> None:
        """Record cost and latency immediately after a validated adapter response."""
        if case_id in self._seen_output_ids:
            return
        self._seen_output_ids.add(case_id)

        cost_relevant = (
            self.policy.max_total_cost_usd is not None
            or self.policy.max_case_cost_usd is not None
        )
        cost_issues: list[str] = []
        cost = _read_non_negative_measurement(
            output.cost_usd, "cost_usd", case_id, cost_issues
        )
        if cost is not None:
            self._known_cost_usd = math.fsum((self._known_cost_usd, cost))
            if (
                self._stop_status is None
                and self.policy.max_case_cost_usd is not None
                and cost > float(self.policy.max_case_cost_usd)
            ):
                self._stop(
                    "BUDGET_LIMIT_REACHED",
                    (
                        f"case {case_id!r} cost {cost:.8g} USD exceeded per-case cap "
                        f"{self.policy.max_case_cost_usd:.8g} USD"
                    ),
                )
            if (
                self._stop_status is None
                and self.policy.max_total_cost_usd is not None
                and self._known_cost_usd >= float(self.policy.max_total_cost_usd)
            ):
                self._stop(
                    "BUDGET_LIMIT_REACHED",
                    (
                        f"known cumulative cost {self._known_cost_usd:.8g} USD reached "
                        f"the total cost cap {self.policy.max_total_cost_usd:.8g} USD"
                    ),
                )
        elif cost_relevant:
            if output.cost_usd is None:
                self._stop(
                    "INCOMPLETE_BUDGET_EVIDENCE",
                    f"case {case_id!r} has no cost measurement required by the live budget policy",
                )
            else:
                self._stop(
                    "INVALID_BUDGET_EVIDENCE",
                    cost_issues[0] if cost_issues else f"case {case_id!r} has invalid cost evidence",
                )

        latency_relevant = self.policy.max_case_latency_ms is not None
        if latency_relevant:
            latency_issues: list[str] = []
            latency = _read_non_negative_measurement(
                output.latency_ms, "latency_ms", case_id, latency_issues
            )
            if latency is None:
                if output.latency_ms is None:
                    self._stop(
                        "INCOMPLETE_BUDGET_EVIDENCE",
                        f"case {case_id!r} has no latency measurement required by the live budget policy",
                    )
                else:
                    self._stop(
                        "INVALID_BUDGET_EVIDENCE",
                        latency_issues[0]
                        if latency_issues
                        else f"case {case_id!r} has invalid latency evidence",
                    )
            elif (
                self._stop_status is None
                and latency > float(self.policy.max_case_latency_ms)
            ):
                self._stop(
                    "BUDGET_LIMIT_REACHED",
                    (
                        f"case {case_id!r} latency {latency:.8g} ms exceeded per-case cap "
                        f"{self.policy.max_case_latency_ms:.8g} ms"
                    ),
                )

    def observe_graders(self, result: CaseResult) -> None:
        """Record grader usage after grading so token limits can stop later cases."""
        case_id = result.case.id
        if case_id in self._seen_usage_ids:
            return
        self._seen_usage_ids.add(case_id)
        tokens, invalid, issue = _read_case_token_usage(result, case_id)
        if tokens is None:
            if self.policy.max_total_tokens is None:
                return
            if invalid:
                self._stop(
                    "INVALID_BUDGET_EVIDENCE",
                    issue or f"case {case_id!r} has invalid token usage evidence",
                )
            else:
                self._stop(
                    "INCOMPLETE_BUDGET_EVIDENCE",
                    issue or f"case {case_id!r} has no token usage required by the live budget policy",
                )
            return

        self._known_tokens += tokens
        if (
            self._stop_status is None
            and self.policy.max_total_tokens is not None
            and self._known_tokens >= self.policy.max_total_tokens
        ):
            self._stop(
                "BUDGET_LIMIT_REACHED",
                (
                    f"known cumulative tokens {self._known_tokens} reached "
                    f"the total token cap {self.policy.max_total_tokens}"
                ),
            )

    def observe_result(self, result: CaseResult) -> None:
        """Account for an already completed result, such as a checkpoint entry."""
        self.observe_output(result.case.id, result.output)
        self.observe_graders(result)

    def finish(self, pending_case_ids: tuple[str, ...]) -> LiveBudgetStatus:
        """Return a status, ensuring unexplained partial results are never called complete."""
        if self._stop_status is not None:
            return self._stop_status
        if pending_case_ids:
            self._stop(
                "INCOMPLETE_BUDGET_EVIDENCE",
                "the run ended with cases not executed and no recorded budget stop reason",
            )
            return self._stop_status or "INCOMPLETE_BUDGET_EVIDENCE"
        return "COMPLETED"

    def _stop(self, status: LiveBudgetStatus, reason: str) -> None:
        if self._stop_status is None:
            self._stop_status = status
            self._stop_reason = reason
