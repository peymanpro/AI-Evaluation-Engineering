"""Case-level comparison of failed graders between two evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass

from .domain import CaseResult, EvaluationRun
from .failure_memory import FailureRecord, extract_failure_records


@dataclass(frozen=True)
class PersistentFailure:
    """A failure observed in both runs, with raw score change for inspection."""

    baseline: FailureRecord
    candidate: FailureRecord

    @property
    def score_delta(self) -> float:
        """Candidate score minus baseline score; interpretation depends on grader."""
        return float(self.candidate.latest_score) - float(self.baseline.latest_score)


@dataclass(frozen=True)
class FailureDeltaReport:
    """A strict comparison of failure sets for two runs of the same test suite."""

    suite_version: str
    system_name: str
    baseline_system_version: str
    candidate_system_version: str
    baseline_run_id: str
    candidate_run_id: str
    new_failures: tuple[FailureRecord, ...]
    resolved_failures: tuple[FailureRecord, ...]
    persistent_failures: tuple[PersistentFailure, ...]

    @property
    def new_failure_count(self) -> int:
        return len(self.new_failures)

    @property
    def resolved_failure_count(self) -> int:
        return len(self.resolved_failures)

    @property
    def persistent_failure_count(self) -> int:
        return len(self.persistent_failures)

    @property
    def has_new_regressions(self) -> bool:
        return bool(self.new_failures)

    @property
    def all_baseline_failures_resolved(self) -> bool:
        return not self.resolved_failures and not self.persistent_failures

    def summary(self) -> str:
        return (
            f"failure delta: {self.new_failure_count} new, "
            f"{self.resolved_failure_count} resolved, "
            f"{self.persistent_failure_count} persistent"
        )


def compare_failure_runs(
    baseline: EvaluationRun,
    candidate: EvaluationRun,
) -> FailureDeltaReport:
    """Compare failures while rejecting test or grader-contract drift.

    Both runs must use the same system name, suite version, unique case IDs,
    identical case definitions, and the same set of grader names for every
    case. This prevents a removed test or omitted grader from being mistaken
    for a resolved failure. Systems may have different version IDs.
    """
    baseline_records = extract_failure_records(baseline)
    candidate_records = extract_failure_records(candidate)

    if baseline.manifest.suite_version != candidate.manifest.suite_version:
        raise ValueError(
            "Cannot compare failure sets from different suite versions "
            f"({baseline.manifest.suite_version!r} vs "
            f"{candidate.manifest.suite_version!r})."
        )
    if baseline.manifest.system_name != candidate.manifest.system_name:
        raise ValueError(
            "Cannot compare failure sets for different system names "
            f"({baseline.manifest.system_name!r} vs "
            f"{candidate.manifest.system_name!r})."
        )

    baseline_cases = {item.case.id: item for item in baseline.cases}
    candidate_cases = {item.case.id: item for item in candidate.cases}
    baseline_ids = set(baseline_cases)
    candidate_ids = set(candidate_cases)
    if baseline_ids != candidate_ids:
        missing_candidate = sorted(baseline_ids - candidate_ids)
        missing_baseline = sorted(candidate_ids - baseline_ids)
        details = []
        if missing_candidate:
            details.append("candidate missing cases: " + ", ".join(missing_candidate))
        if missing_baseline:
            details.append("candidate has unmatched cases: " + ", ".join(missing_baseline))
        raise ValueError("Cannot compare failure sets with different case IDs (" + "; ".join(details) + ").")

    for case_id in sorted(baseline_ids):
        before = baseline_cases[case_id]
        after = candidate_cases[case_id]
        if before.case != after.case:
            raise ValueError(
                f"Cannot compare failure sets because case definition changed for {case_id!r}."
            )
        before_graders = {grader.grader for grader in before.graders}
        after_graders = {grader.grader for grader in after.graders}
        if before_graders != after_graders:
            missing = sorted(before_graders - after_graders)
            added = sorted(after_graders - before_graders)
            details = []
            if missing:
                details.append("candidate missing graders: " + ", ".join(missing))
            if added:
                details.append("candidate added graders: " + ", ".join(added))
            raise ValueError(
                f"Cannot compare failure sets because grader set changed for {case_id!r} "
                f"(" + "; ".join(details) + ")."
            )

    baseline_by_id = _index_records(baseline_records, "baseline")
    candidate_by_id = _index_records(candidate_records, "candidate")
    baseline_failure_ids = set(baseline_by_id)
    candidate_failure_ids = set(candidate_by_id)

    new_failures = tuple(
        candidate_by_id[failure_id]
        for failure_id in sorted(candidate_failure_ids - baseline_failure_ids)
    )
    resolved_failures = tuple(
        baseline_by_id[failure_id]
        for failure_id in sorted(baseline_failure_ids - candidate_failure_ids)
    )
    persistent_failures = tuple(
        PersistentFailure(
            baseline=baseline_by_id[failure_id],
            candidate=candidate_by_id[failure_id],
        )
        for failure_id in sorted(baseline_failure_ids & candidate_failure_ids)
    )

    return FailureDeltaReport(
        suite_version=baseline.manifest.suite_version,
        system_name=baseline.manifest.system_name,
        baseline_system_version=baseline.manifest.system_version,
        candidate_system_version=candidate.manifest.system_version,
        baseline_run_id=baseline.manifest.run_id,
        candidate_run_id=candidate.manifest.run_id,
        new_failures=new_failures,
        resolved_failures=resolved_failures,
        persistent_failures=persistent_failures,
    )


def _index_records(
    records: tuple[FailureRecord, ...],
    label: str,
) -> dict[str, FailureRecord]:
    indexed: dict[str, FailureRecord] = {}
    for record in records:
        if record.failure_id in indexed:
            raise ValueError(
                f"{label} run contains duplicate failure identity {record.failure_id!r}."
            )
        indexed[record.failure_id] = record
    return indexed
