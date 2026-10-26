"""Evaluation adapters and deterministic suite execution."""

from __future__ import annotations

import hashlib
import json
import platform
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .budget import (
    BudgetedRunResult,
    RequestBudgetExceeded,
    ReservedBudgetPolicy,
    ReservedBudgetRunResult,
    RunBudgetPolicy,
    _LiveBudgetGuard,
    _ReservedBudgetController,
)
from .checkpoint import load_run_checkpoint, save_run_checkpoint
from .contracts import validate_grader_results, validate_run_inputs, validate_system_output
from .domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationSuite,
    GraderResult,
    JsonObject,
    RunMetadata,
    SystemOutput,
)
from .retry import RetryPolicy, validate_retry_policy_manifest


class SystemAdapter(Protocol):
    def run(self, case: EvaluationCase) -> SystemOutput:
        ...


class Grader(Protocol):
    def grade(self, case: EvaluationCase, output: SystemOutput) -> GraderResult:
        ...


def configuration_hash(configuration: JsonObject) -> str:
    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def build_run_metadata(
    suite: EvaluationSuite,
    system_name: str,
    system_version: str,
    configuration: JsonObject | None = None,
    seed: int | None = None,
    *,
    retry_policy: RetryPolicy | None = None,
) -> RunMetadata:
    config = dict(configuration or {})
    if retry_policy is not None:
        if not isinstance(retry_policy, RetryPolicy):
            raise TypeError("retry_policy must be a RetryPolicy or None.")
        retry_settings = retry_policy.to_dict()
        if "retry_policy" in config and config["retry_policy"] != retry_settings:
            raise ValueError("configuration.retry_policy does not match retry_policy.")
        config["retry_policy"] = retry_settings
    return RunMetadata(
        run_id=str(uuid.uuid4()),
        suite_version=suite.version,
        system_name=system_name,
        system_version=system_version,
        configuration={**config, "configuration_hash": configuration_hash(config)},
        seed=seed,
        timestamp_utc=datetime.now(UTC).isoformat(),
        environment={"python": platform.python_version(), "platform": platform.platform()},
    )


class EvaluationRunner:
    def __init__(
        self,
        adapter: SystemAdapter,
        graders: list[Grader],
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if not graders:
            raise ValueError("At least one grader is required.")
        if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
            raise TypeError("retry_policy must be a RetryPolicy or None.")
        self._adapter = adapter
        self._graders = graders
        self._retry_policy = retry_policy

    def _run_adapter(self, case: EvaluationCase) -> SystemOutput:
        attempts = self._retry_policy.max_attempts if self._retry_policy else 1
        for attempt in range(1, attempts + 1):
            try:
                return self._adapter.run(case)
            except Exception as exc:
                if self._retry_policy is None:
                    raise
                delay = self._retry_policy.schedule_retry(case.id, exc, attempt)
                if delay is None:
                    raise
                time.sleep(delay)
        raise RuntimeError("Adapter retry loop finished without a result.")

    def run(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        checkpoint_path: str | Path | None = None,
    ) -> EvaluationRun:
        """Run the suite, optionally saving each completed case for later resume.

        When a checkpoint path is supplied, completed cases are written atomically
        after grading. A subsequent invocation validates the suite fingerprint,
        system identity, configuration, and environment before reusing those cases.
        """
        validate_run_inputs(suite, manifest)
        validate_retry_policy_manifest(manifest.configuration, self._retry_policy)
        run_manifest = manifest
        completed: dict[str, CaseResult] = {}
        if checkpoint_path is not None:
            run_manifest, completed = load_run_checkpoint(checkpoint_path, suite, manifest)

        for case in suite.cases:
            if case.id in completed:
                continue
            output = self._run_adapter(case)
            validate_system_output(case, output)
            grader_results = tuple(grader.grade(case, output) for grader in self._graders)
            validate_grader_results(grader_results, case.id)
            completed[case.id] = CaseResult(
                case=case,
                output=output,
                graders=grader_results,
            )
            if checkpoint_path is not None:
                save_run_checkpoint(checkpoint_path, suite, run_manifest, completed)

        return EvaluationRun(
            manifest=run_manifest,
            cases=tuple(completed[case.id] for case in suite.cases),
        )


    def run_budgeted(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        policy: RunBudgetPolicy,
        checkpoint_path: str | Path | None = None,
    ) -> BudgetedRunResult:
        """Run cases until a live budget guard stops scheduling new work.

        This opt-in method can return a partial result when the budget is reached
        or required usage evidence is missing. Partial results are not represented
        as an EvaluationRun. Cost/latency measurements are observed after each
        adapter response; token usage is observed after grading.
        """
        validate_run_inputs(suite, manifest)
        validate_retry_policy_manifest(manifest.configuration, self._retry_policy)
        if not isinstance(policy, RunBudgetPolicy):
            raise TypeError("policy must be a RunBudgetPolicy.")

        run_manifest = manifest
        completed: dict[str, CaseResult] = {}
        if checkpoint_path is not None:
            run_manifest, completed = load_run_checkpoint(checkpoint_path, suite, manifest)

        guard = _LiveBudgetGuard(policy)
        for case in suite.cases:
            saved_result = completed.get(case.id)
            if saved_result is not None:
                guard.observe_result(saved_result)

        for case in suite.cases:
            if case.id in completed:
                continue
            if not guard.can_start_case():
                break

            output = self._run_adapter(case)
            validate_system_output(case, output)
            guard.observe_output(case.id, output)
            grader_results = tuple(grader.grade(case, output) for grader in self._graders)
            validate_grader_results(grader_results, case.id)
            case_result = CaseResult(
                case=case,
                output=output,
                graders=grader_results,
            )
            guard.observe_graders(case_result)
            completed[case.id] = case_result
            if checkpoint_path is not None:
                save_run_checkpoint(checkpoint_path, suite, run_manifest, completed)

        ordered_completed = tuple(
            completed[case.id] for case in suite.cases if case.id in completed
        )
        pending_case_ids = tuple(
            case.id for case in suite.cases if case.id not in completed
        )
        status = guard.finish(
            pending_case_ids, completed_case_count=len(ordered_completed)
        )
        return BudgetedRunResult(
            manifest=run_manifest,
            completed_cases=ordered_completed,
            pending_case_ids=pending_case_ids,
            status=status,
            known_cost_usd=guard.known_cost_usd,
            known_tokens=guard.known_tokens,
            stop_reason=guard.stop_reason,
        )


    def run_reserved_budgeted(
        self,
        suite: EvaluationSuite,
        manifest: RunMetadata,
        *,
        policy: ReservedBudgetPolicy,
        checkpoint_path: str | Path | None = None,
    ) -> ReservedBudgetRunResult:
        """Execute only through components that honor pre-request cost ceilings.

        Every billable adapter/grader must accept a `max_cost_usd` argument and
        enforce it before making provider calls. Deterministic graders may opt in
        with `budget_cost_free = True`. Retries are disabled because a failed
        request may already have been billed.
        """
        validate_run_inputs(suite, manifest)
        if not isinstance(policy, ReservedBudgetPolicy):
            raise TypeError("policy must be a ReservedBudgetPolicy.")
        if self._retry_policy is not None:
            raise ValueError(
                "run_reserved_budgeted does not allow retries; an attempted request may already be billed."
            )
        adapter_call = getattr(self._adapter, "run_with_budget", None)
        if not callable(adapter_call):
            raise TypeError(
                "run_reserved_budgeted requires an adapter implementing "
                "run_with_budget(case, *, max_cost_usd); ordinary adapters are not safe for reserved mode."
            )
        for grader in self._graders:
            if getattr(grader, "budget_cost_free", False) is True:
                continue
            if not callable(getattr(grader, "grade_with_budget", None)):
                raise TypeError(
                    f"grader {type(grader).__name__} must implement grade_with_budget "
                    "or explicitly declare budget_cost_free = True."
                )

        run_manifest = manifest
        completed: dict[str, CaseResult] = {}
        if checkpoint_path is not None:
            run_manifest, completed = load_run_checkpoint(checkpoint_path, suite, manifest)

        controller = _ReservedBudgetController(policy)
        for case in suite.cases:
            saved = completed.get(case.id)
            if saved is None:
                continue
            case_spent = controller.record_existing_component_cost(
                saved.output.cost_usd,
                case_id=case.id,
                source="system adapter",
                case_spent_usd=0.0,
            )
            if case_spent is None:
                continue
            for grader, grader_result in zip(self._graders, saved.graders, strict=True):
                if getattr(grader, "budget_cost_free", False) is True:
                    continue
                grader_cost = controller.record_existing_component_cost(
                    grader_result.metadata.get("cost_usd"),
                    case_id=case.id,
                    source=f"grader {grader_result.grader!r}",
                    case_spent_usd=case_spent,
                )
                if grader_cost is None:
                    break
                case_spent = math.fsum((case_spent, grader_cost))
            if case_spent > float(policy.max_case_cost_usd):
                controller.stop(
                    "REQUEST_CAP_VIOLATED",
                    f"checkpoint case {case.id!r} exceeds its configured case cost cap",
                )

        for case in suite.cases:
            if case.id in completed or controller.stop_status is not None:
                continue
            allocation = controller.reserve_case()
            if allocation is None:
                break
            case_spent = 0.0
            try:
                output = adapter_call(case, max_cost_usd=allocation)
            except RequestBudgetExceeded as exc:
                controller.stop(
                    "BUDGET_LIMIT_REACHED",
                    f"adapter declined case {case.id!r} before sending a request: {exc}",
                )
                controller.release_case(allocation, case_spent)
                break

            validate_system_output(case, output)
            output_cost = controller.record_component_cost(
                output.cost_usd,
                case_id=case.id,
                source="system adapter",
                allocation_usd=allocation,
                case_spent_usd=case_spent,
            )
            if output_cost is None:
                # Keep the remaining reservation: real spend is unknown.
                break
            case_spent = math.fsum((case_spent, output_cost))
            if controller.stop_status is not None:
                controller.release_case(allocation, case_spent)
                break

            grader_results: list[GraderResult] = []
            for grader in self._graders:
                if controller.stop_status is not None:
                    break
                if getattr(grader, "budget_cost_free", False) is True:
                    grader_result = grader.grade(case, output)
                    if not isinstance(grader_result, GraderResult):
                        raise TypeError("Graders must return GraderResult instances.")
                    grader_results.append(grader_result)
                    continue

                remaining_case_budget = max(0.0, allocation - case_spent)
                if remaining_case_budget <= 0.0:
                    controller.stop(
                        "BUDGET_LIMIT_REACHED",
                        f"no case budget remains for grader {type(grader).__name__} on case {case.id!r}",
                    )
                    break
                try:
                    grader_result = grader.grade_with_budget(
                        case, output, max_cost_usd=remaining_case_budget
                    )
                except RequestBudgetExceeded as exc:
                    controller.stop(
                        "BUDGET_LIMIT_REACHED",
                        f"grader declined case {case.id!r} before sending a request: {exc}",
                    )
                    break
                if not isinstance(grader_result, GraderResult):
                    raise TypeError("Budget-aware graders must return GraderResult instances.")
                grader_cost = controller.record_component_cost(
                    grader_result.metadata.get("cost_usd"),
                    case_id=case.id,
                    source=f"grader {grader_result.grader!r}",
                    allocation_usd=allocation,
                    case_spent_usd=case_spent,
                )
                if grader_cost is None:
                    # Keep the remaining reservation until accounting is reconciled.
                    break
                case_spent = math.fsum((case_spent, grader_cost))
                grader_results.append(grader_result)
                if controller.stop_status is not None:
                    break

            if len(grader_results) != len(self._graders):
                if controller.stop_status is None:
                    controller.stop(
                        "INCOMPLETE_BUDGET_EVIDENCE",
                        f"case {case.id!r} did not complete every grader",
                    )
                if controller.stop_status in (
                    "BUDGET_LIMIT_REACHED",
                    "REQUEST_CAP_VIOLATED",
                ):
                    controller.release_case(allocation, case_spent)
                break

            graded = tuple(grader_results)
            validate_grader_results(graded, case.id)
            case_result = CaseResult(case=case, output=output, graders=graded)
            completed[case.id] = case_result
            if checkpoint_path is not None:
                save_run_checkpoint(checkpoint_path, suite, run_manifest, completed)
            controller.release_case(allocation, case_spent)

        ordered_completed = tuple(
            completed[case.id] for case in suite.cases if case.id in completed
        )
        pending_case_ids = tuple(
            case.id for case in suite.cases if case.id not in completed
        )
        status = controller.finish(
            pending_case_ids=pending_case_ids,
            completed_case_count=len(ordered_completed),
        )
        return ReservedBudgetRunResult(
            manifest=run_manifest,
            completed_cases=ordered_completed,
            pending_case_ids=pending_case_ids,
            status=status,
            known_cost_usd=controller.known_cost_usd,
            reserved_cost_usd=controller.reserved_cost_usd,
            stop_reason=controller.stop_reason,
        )


def persist_run(run: EvaluationRun, path: str | Path) -> None:
    payload = {
        "manifest": _jsonify(run.manifest),
        "cases": [_jsonify(result) for result in run.cases],
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _jsonify(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonify(field) for key, field in vars(value).items()}
    if isinstance(value, tuple):
        return [_jsonify(item) for item in value]
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    return value
