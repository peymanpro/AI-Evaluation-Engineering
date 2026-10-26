"""Command-line tools for working with recorded AI evaluation runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .budget import RunBudgetPolicy, assess_run_budget
from .release_gate import ReleaseMetricPolicy, evaluate_release_candidate
from .result_import import get_external_run_schema, load_run_json
from .suite_io import get_evaluation_suite_schema, load_suite_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-eval",
        description=(
            "Validate, compare, and budget-check recorded AI evaluation runs. "
            "Commands make no provider calls."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser(
        "validate-run",
        help="validate a versioned external-run JSON file and print its manifest summary",
    )
    validate.add_argument("path", type=Path, help="path to an external-run-v1 JSON file")

    commands.add_parser(
        "schema",
        help="print the packaged external-run JSON Schema",
    )

    commands.add_parser(
        "suite-schema",
        help="print the packaged evaluation-suite JSON Schema",
    )

    validate_suite = commands.add_parser(
        "validate-suite",
        help="validate a versioned evaluation-suite JSON file",
    )
    validate_suite.add_argument("path", type=Path, help="path to an evaluation-suite-v1 JSON file")

    compare = commands.add_parser(
        "compare",
        help="compare baseline and candidate run JSON files with a release gate",
    )
    compare.add_argument("baseline", type=Path, help="baseline external-run-v1 JSON")
    compare.add_argument("candidate", type=Path, help="candidate external-run-v1 JSON")
    compare.add_argument("--metric", required=True, help="grader name whose numeric score is gated")
    compare.add_argument(
        "--direction",
        choices=("higher_is_better", "lower_is_better"),
        default="higher_is_better",
    )
    compare.add_argument("--max-allowed-regression", type=float, default=0.0)
    compare.add_argument("--min-cases", type=int, default=30)
    compare.add_argument("--confidence", type=float, default=0.95)
    compare.add_argument("--resamples", type=int, default=2000)
    compare.add_argument("--seed", type=int, default=0)

    budget = commands.add_parser(
        "budget",
        help="assess recorded cost, token usage, and latency against explicit limits",
    )
    budget.add_argument("path", type=Path, help="external-run-v1 JSON file")
    budget.add_argument("--max-total-cost-usd", type=float)
    budget.add_argument("--max-case-cost-usd", type=float)
    budget.add_argument("--max-total-tokens", type=int)
    budget.add_argument("--max-case-latency-ms", type=float)

    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _validate_run(path: Path) -> int:
    run = load_run_json(path)
    grader_names = sorted(
        {grader.grader for case_result in run.cases for grader in case_result.graders}
    )
    _print_json(
        {
            "status": "VALID",
            "run_id": run.manifest.run_id,
            "system_name": run.manifest.system_name,
            "system_version": run.manifest.system_version,
            "suite_version": run.manifest.suite_version,
            "case_count": len(run.cases),
            "grader_names": grader_names,
        }
    )
    return 0


def _validate_suite(path: Path) -> int:
    suite = load_suite_json(path)
    tag_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for case in suite.cases:
        for tag in case.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if case.risk_category is not None:
            risk_counts[case.risk_category] = risk_counts.get(case.risk_category, 0) + 1
    _print_json(
        {
            "status": "VALID",
            "suite_version": suite.version,
            "case_count": len(suite.cases),
            "tag_counts": dict(sorted(tag_counts.items())),
            "risk_category_counts": dict(sorted(risk_counts.items())),
        }
    )
    return 0


def _compare_runs(args: argparse.Namespace) -> int:
    baseline = load_run_json(args.baseline)
    candidate = load_run_json(args.candidate)
    policy = ReleaseMetricPolicy(
        metric=args.metric,
        direction=args.direction,
        max_allowed_regression=args.max_allowed_regression,
        min_cases=args.min_cases,
    )
    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [policy],
        confidence=args.confidence,
        resamples=args.resamples,
        seed=args.seed,
    )
    _print_json(asdict(decision))
    return 0 if decision.status == "PASS" else 1


def _assess_budget(args: argparse.Namespace) -> int:
    run = load_run_json(args.path)
    policy = RunBudgetPolicy(
        max_total_cost_usd=args.max_total_cost_usd,
        max_case_cost_usd=args.max_case_cost_usd,
        max_total_tokens=args.max_total_tokens,
        max_case_latency_ms=args.max_case_latency_ms,
    )
    assessment = assess_run_budget(run, policy)
    _print_json(asdict(assessment))
    return 0 if assessment.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; return a shell-friendly exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            _print_json(get_external_run_schema())
            return 0
        if args.command == "suite-schema":
            _print_json(get_evaluation_suite_schema())
            return 0
        if args.command == "validate-suite":
            return _validate_suite(args.path)
        if args.command == "validate-run":
            return _validate_run(args.path)
        if args.command == "compare":
            return _compare_runs(args)
        if args.command == "budget":
            return _assess_budget(args)
        parser.error(f"unsupported command {args.command!r}")
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"ai-eval: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
