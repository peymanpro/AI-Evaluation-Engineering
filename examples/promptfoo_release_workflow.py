"""Compare two Promptfoo v3 JSON exports using release and failure-delta gates.

The default files are deterministic synthetic fixtures used in CI. Pass real
Promptfoo exports as positional paths to run the same workflow on your own data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_eval_engineering import (
    ReleaseMetricPolicy,
    compare_failure_runs,
    evaluate_release_candidate,
    load_promptfoo_json,
)
from ai_eval_engineering.domain import EvaluationRun

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "tests" / "fixtures" / "promptfoo-baseline-v3.json"
DEFAULT_CANDIDATE = ROOT / "tests" / "fixtures" / "promptfoo-candidate-v3.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import Promptfoo v3 exports, compare a candidate with its baseline, "
            "and report both release-gate status and case-level failure changes."
        )
    )
    parser.add_argument(
        "baseline",
        nargs="?",
        type=Path,
        default=DEFAULT_BASELINE,
        help="baseline Promptfoo v3 JSON (defaults to the committed demo fixture)",
    )
    parser.add_argument(
        "candidate",
        nargs="?",
        type=Path,
        default=DEFAULT_CANDIDATE,
        help="candidate Promptfoo v3 JSON (defaults to the committed demo fixture)",
    )
    parser.add_argument("--system-name", default="arithmetic-assistant")
    parser.add_argument("--baseline-version", default="model-v1")
    parser.add_argument("--candidate-version", default="model-v2")
    parser.add_argument("--suite-version", default="arithmetic-suite-v1")
    parser.add_argument("--provider-id", default="openai:mock:answerer")
    parser.add_argument("--prompt-idx", type=int, default=0)
    parser.add_argument("--max-allowed-regression", type=float, default=0.02)
    parser.add_argument("--min-cases", type=int, default=30)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--enforce-gate",
        action="store_true",
        help="exit with status 1 if the decision is FAIL or INCONCLUSIVE",
    )
    return parser.parse_args(argv)


def _load_run(
    path: Path,
    *,
    system_name: str,
    system_version: str,
    suite_version: str,
    provider_id: str,
    prompt_idx: int,
) -> EvaluationRun:
    return load_promptfoo_json(
        path,
        system_name=system_name,
        system_version=system_version,
        suite_version=suite_version,
        provider_id=provider_id,
        prompt_idx=prompt_idx,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        baseline = _load_run(
            args.baseline,
            system_name=args.system_name,
            system_version=args.baseline_version,
            suite_version=args.suite_version,
            provider_id=args.provider_id,
            prompt_idx=args.prompt_idx,
        )
        candidate = _load_run(
            args.candidate,
            system_name=args.system_name,
            system_version=args.candidate_version,
            suite_version=args.suite_version,
            provider_id=args.provider_id,
            prompt_idx=args.prompt_idx,
        )
        decision = evaluate_release_candidate(
            baseline,
            candidate,
            [
                ReleaseMetricPolicy(
                    "promptfoo",
                    direction="higher_is_better",
                    max_allowed_regression=args.max_allowed_regression,
                    min_cases=args.min_cases,
                )
            ],
            confidence=0.95,
            resamples=args.resamples,
            seed=args.seed,
        )
        delta = compare_failure_runs(baseline, candidate)
    except (OSError, TypeError, ValueError) as exc:
        print(f"Unable to compare Promptfoo exports: {exc}", file=sys.stderr)
        return 2

    print("Promptfoo baseline vs candidate")
    print(
        f"Baseline:  {baseline.manifest.system_version} | "
        f"{len(baseline.cases)} cases | {args.baseline}"
    )
    print(
        f"Candidate: {candidate.manifest.system_version} | "
        f"{len(candidate.cases)} cases | {args.candidate}"
    )
    print()
    print(f"Release decision: {decision.status}")
    print(decision.summary())
    for metric in decision.metrics:
        interval = metric.confidence_interval
        interval_text = (
            "not available"
            if interval is None
            else f"[{interval.lower:.4f}, {interval.upper:.4f}]"
        )
        print(
            f"  {metric.metric}: baseline={metric.baseline_mean:.4f}, "
            f"candidate={metric.candidate_mean:.4f}, "
            f"delta={metric.observed_difference:+.4f}, "
            f"95% CI={interval_text}, n={metric.sample_size}"
        )
    print()
    print(delta.summary())

    for failure in delta.new_failures:
        print(
            f"  NEW       {failure.case.id} / {failure.grader}: "
            f"{failure.latest_details}"
        )
    for failure in delta.resolved_failures:
        print(
            f"  RESOLVED  {failure.case.id} / {failure.grader}: "
            f"{failure.latest_details}"
        )
    for failure in delta.persistent_failures:
        print(
            f"  PERSISTENT {failure.candidate.case.id} / "
            f"{failure.candidate.grader}: score delta={failure.score_delta:+.4f}"
        )

    if decision.status == "INVALID_EVIDENCE":
        return 2
    if args.enforce_gate and decision.status != "PASS":
        print("Enforced release gate rejected the candidate.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
