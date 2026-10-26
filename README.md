# AI Evaluation Engineering

**AI Evaluation Engineering is a provider-neutral Python library for evaluating, comparing, and regression-testing AI systems.** It provides reusable evaluation contracts, synchronous and asynchronous runners, graders, statistical release gates, budget controls, and auditable run artifacts—so AI evaluation can be part of a repeatable engineering workflow rather than a collection of one-off scripts.

[![Python 3.11–3.13 tested](https://img.shields.io/badge/python-3.11--3.13-3776AB.svg)](https://www.python.org/)
[![CI](https://github.com/peymanpro/AI-Evaluation-Engineering/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/peymanpro/AI-Evaluation-Engineering/actions/workflows/ci.yml)
[![Latest GitHub Release](https://img.shields.io/github/v/release/peymanpro/AI-Evaluation-Engineering)](https://github.com/peymanpro/AI-Evaluation-Engineering/releases)
[![PyPI project](https://img.shields.io/badge/PyPI-ai--evaluation--engineering-3775A9.svg)](https://pypi.org/project/ai-evaluation-engineering/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

The library keeps case-level observations and run metadata available for inspection. It helps teams answer not only *“What score did this model get?”*, but also *“Which cases failed, how certain is the comparison, what did the run cost, and is the evidence complete enough to support a release decision?”*

It is an evaluation library—not a hosted experimentation platform, model-serving system, or guarantee of production quality.

## Table of contents

- [Why this library exists](#why-this-library-exists)
- [Capabilities](#capabilities)
- [Installation](#installation)
- [Quick start](#quick-start)
- [How the library works](#how-the-library-works)
- [Core data model](#core-data-model)
- [Evaluation suites and data contracts](#evaluation-suites-and-data-contracts)
- [Grading](#grading)
- [Asynchronous execution, retries, and checkpoints](#asynchronous-execution-retries-and-checkpoints)
- [Budget controls](#budget-controls)
- [Failure-aware execution reports](#failure-aware-execution-reports)
- [Comparisons and release policies](#comparisons-and-release-policies)
- [Command-line interface](#command-line-interface)
- [LLM-as-a-judge](#llm-as-a-judge)
- [Agent, security, online, and trade-off evaluation](#agent-security-online-and-trade-off-evaluation)
- [Integrations](#integrations)
- [Evidence and methodology](#evidence-and-methodology)
- [Limitations and non-goals](#limitations-and-non-goals)
- [Development](#development)
- [Release status](#release-status)

## Why this library exists

A benchmark script can produce a score, but a reliable engineering workflow needs more context: a stable test population, a known system revision, validated outputs, case-level results, appropriate uncertainty estimates, and explicit rules for deciding whether a change is acceptable.

AI Evaluation Engineering brings those pieces into one provider-neutral Python API:

1. Define cases and a versioned evaluation suite.
2. Run a system adapter and record its outputs.
3. Grade each case with deterministic checks, a configured judge, or a combination.
4. Preserve results and metadata so runs can be inspected or resumed.
5. Compare baseline and candidate runs using explicit metrics and release policies.
6. Export evidence for CI, debugging, and later review.

The library separates **execution**, **grading**, **statistical interpretation**, and **release decisions**. A successful test run verifies the implemented contracts and examples; it does not by itself prove that an evaluation suite represents production traffic or that a model is safe in every setting.

## Capabilities

| Area | What the library provides |
| --- | --- |
| Evaluation core | Typed cases, suites, run manifests, system outputs, grader results, and recorded runs |
| Execution | Synchronous and bounded-concurrency asynchronous runners, optional per-attempt deadlines, and resumable checkpoints |
| Grading | Exact-match, substring, regex, numeric-tolerance, JSON-field, schema, rule-based, trajectory, and composite graders |
| Model-based judging | Optional synchronous and native-async OpenAI-compatible judges with structured outputs |
| Data interchange | Strict, versioned JSON contracts for suites, recorded runs, release policies, and execution reports; Promptfoo v3 result import |
| Failure handling | Explicit per-case execution reports, failure-delta comparisons, and persistent failure memory |
| Budget visibility | Post-run assessments, observed-usage scheduling guards, and reservation-based budget execution for components that enforce request ceilings |
| Statistical decisions | Paired comparisons, bootstrap confidence intervals, direction-aware metric policies, and multi-metric release gates |
| Diagnostics | Offline slice analysis by tags, risk categories, or explicitly selected case-metadata fields |
| Other evaluation views | Agent trajectories, adversarial test fixtures, online-evaluation primitives, and quality/cost or quality/latency trade-off frontiers |
| Evidence | Machine-readable run records and auditable evidence packages |

## Installation

**The `v0.3.0` GitHub Release is available, but the initial PyPI upload is still pending.** The [PyPI project page](https://pypi.org/project/ai-evaluation-engineering/) is the intended installation target. Until the first upload succeeds, install from a source checkout. Once published, the package can be installed with `python -m pip install ai-evaluation-engineering`.

~~~bash
git clone https://github.com/peymanpro/AI-Evaluation-Engineering.git
cd AI-Evaluation-Engineering
python -m pip install -e .
~~~

For tests and development tools:

~~~bash
python -m pip install -e ".[dev]"
~~~

For the optional OpenAI-compatible LLM judge:

~~~bash
python -m pip install -e ".[openai]"
~~~

To install the development tools and optional judge SDK together:

~~~bash
python -m pip install -e ".[dev,openai]"
~~~

The core library has no mandatory third-party runtime dependencies. The OpenAI SDK is optional and is needed only for the provider-backed judge integration.

## Quick start

The following example runs a small, deterministic fixture. Replace the demo adapter with an adapter for the system you actually want to evaluate.

~~~python
from ai_eval_engineering import (
    AggregatedResult,
    EvaluationCase,
    EvaluationRunner,
    EvaluationSuite,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


class DemoAdapter:
    """A synthetic adapter; it does not call an external model."""

    def run(self, case: EvaluationCase) -> SystemOutput:
        return SystemOutput(
            case_id=case.id,
            output=case.input["answer"],
            latency_ms=1.0,
            cost_usd=0.0,
        )


suite = EvaluationSuite(
    version="support-smoke-v1",
    cases=(
        EvaluationCase(
            id="capital-of-france",
            input={"question": "What is the capital of France?", "answer": "Paris"},
            expected="Paris",
            tags=("smoke",),
        ),
    ),
)

manifest = build_run_metadata(
    suite,
    system_name="demo-system",
    system_version="demo-1",
    configuration={"adapter": "synthetic"},
    seed=7,
)

runner = EvaluationRunner(DemoAdapter(), [ExactMatchGrader()])
run = runner.run(suite, manifest)
summary = AggregatedResult.from_case_results(list(run.cases))

print(run.manifest.run_id)
print(f"Pass rate: {summary.pass_rate:.0%}")
print(f"Mean score: {summary.mean_score:.3f}")
~~~

Expected output includes a pass rate of `100%` and a mean score of `1.000`. The values are deterministic because this example uses a synthetic adapter; they are not a benchmark claim about a real model.

## How the library works

~~~text
Evaluation suite + run manifest
             |
             v
      System adapter
             |
             v
    Validated system output
             |
             v
           Graders
             |
             v
     Recorded case results
             |
             v
 Statistical comparison / diagnostics
             |
             v
     Release gate + evidence
~~~

The system adapter is the boundary to the system under test. It can wrap an API, local application, agent runtime, or deterministic fixture. The evaluation library validates the adapter's outputs and does not need to own or host the evaluated system.

## Core data model

| Type | Role |
| --- | --- |
| `EvaluationCase` | One input, expected value, tags, metadata, and optional risk category |
| `EvaluationSuite` | A versioned collection of evaluation cases |
| `RunMetadata` | Run identity, suite version, system name and version, configuration, seed, timestamp, and environment |
| `SystemOutput` | Output plus optional latency, measured cost, and trace |
| `GraderResult` | A named pass/fail result, numeric score, explanation, and metadata |
| `EvaluationRun` | A complete manifest and the recorded results for its cases |
| `EvaluationExecutionReport` | Ordered complete or failed per-case outcomes when using `run_report()` |

This separation keeps suite data reusable and makes each recorded result traceable to the system version and configuration that produced it.

## Evaluation suites and data contracts

Versioned JSON suites make test cases reviewable and reusable without embedding executable Python in the data file. A suite file holds case definitions; configure adapters and graders in code.

~~~python
from ai_eval_engineering import load_suite_json, write_suite_json

suite = load_suite_json("examples/suites/support-smoke-v1.json")
print(suite.version, len(suite.cases))

# Write a modified suite using an atomic file replacement.
write_suite_json(suite, "data/support-suite-v1.json")
~~~

Validate the included example and inspect the packaged schema:

~~~bash
ai-eval validate-suite examples/suites/support-smoke-v1.json
ai-eval suite-schema > evaluation-suite-v1.schema.json
~~~

The versioned importers validate structured contract boundaries, reject unknown fields at those boundaries, reject unsupported schema versions and malformed or non-finite evidence, and detect duplicate case or grader identifiers where uniqueness is required. Application-owned JSON objects—such as case inputs, expected values, outputs, and metadata—remain extensible.

The versioned interchange formats include:

- **`evaluation-suite-v1`** — reusable suite definitions.
- **`external-run-v1`** — normalized recorded results, including results imported from external evaluators.
- **`release-policy-v1`** — reproducible settings for multi-metric release decisions.
- **`execution-report-v1`** — complete or partial per-case execution outcomes, including captured failures.

Schemas are available from the installed package. For example, use `get_evaluation_suite_schema()`, `get_external_run_schema()`, `get_release_policy_schema()`, or `get_execution_report_schema()` when another tool needs to validate a file before importing it.

## Grading

Choose a grader based on the evidence you need. Deterministic graders are preferable when the expected behavior can be expressed precisely; they do not require a second model call.

### Deterministic graders

The library includes:

- **Exact match** — compare expected and actual values, with configurable normalization.
- **Substring** — check for an expected or configured substring.
- **Regular expression** — check a pattern using search or full-match semantics.
- **Numeric tolerance** — compare finite numeric values using explicit absolute and relative tolerances.
- **JSON field** — compare a value at a JSON Pointer path such as `/decision` or `/items/0/id`.
- **Composite** — combine named graders with explicit weights and an `all`, `any`, or score-threshold pass rule.
- **Schema, rule-based, and trajectory graders** — validate structured outputs, custom rules, and agent execution traces.

Example of grading structured output:

~~~python
from ai_eval_engineering import CompositeGrader, JsonFieldGrader
from ai_eval_engineering.domain import EvaluationCase, SystemOutput

case = EvaluationCase("refund-decision", {}, expected=None)
output = SystemOutput(
    "refund-decision",
    {"decision": "approved", "safety": {"allowed": True}},
)

grader = CompositeGrader(
    [
        JsonFieldGrader("/decision", name="decision", expected_value="approved"),
        JsonFieldGrader("/safety/allowed", name="safety", expected_value=True),
    ],
    weights=[0.75, 0.25],
    pass_mode="all",
)

result = grader.grade(case, output)
print(result.passed, result.score)
~~~

Composite scores must be finite values in `[0, 1]`, and component grader names must be unique. A passing flag and a numeric score are separate fields; their relationship should follow an explicit grader contract.

### Versioned external-run interchange

Use `load_run_json()` and `write_run_json()` to import and export normalized run records. The `Promptfoo v3` adapter supports importing its documented JSON result format; it is an interchange adapter, not a replacement for the external evaluator.

~~~python
from ai_eval_engineering import load_run_json, write_run_json

run = load_run_json("external-results/candidate-run.json")
write_run_json(run, "normalized/candidate-run.json")
print(run.manifest.system_version, len(run.cases))
~~~

The normalized run schema can be obtained with `get_external_run_schema()`. An external tool remains responsible for mapping its result fields into the documented envelope. Unknown schema versions fail explicitly rather than being guessed.

## Asynchronous execution, retries, and checkpoints

### Asynchronous runner

`AsyncEvaluationRunner` supports bounded concurrency and returns results in suite order. It can apply a per-case adapter deadline and supports synchronous graders or awaitable grader results.

~~~python
run = await AsyncEvaluationRunner(
    async_adapter,
    graders,
    max_concurrency=8,
    timeout_per_case_seconds=30.0,
).run(suite, manifest)
~~~

### Explicit retry policy

Retries are opt-in and wrap the system-adapter call only. A `RetryPolicy` lets callers choose the attempt limit, retryable exception classes, bounded backoff, and an optional retry-event callback. Grading and output validation are not retried. The configured policy is recorded in the run manifest and checked when running or resuming.

A timeout or connection failure can happen after a provider has processed and billed a request. Retrying can therefore duplicate spend or side effects. Configure retryable exceptions deliberately and use provider-supported idempotency keys when available. This feature is not a rate limiter, circuit breaker, or spend limiter.

### Resumable runs

Pass `checkpoint_path` to `run()` or `run_report()` to persist completed cases atomically and reuse them after a later failure. Before resuming, the library validates the suite fingerprint and run identity, including system, version, configuration, seed, and environment. Only unfinished or failed cases are attempted again.

Checkpoints can contain prompts, inputs, expected values, outputs, traces, and grader details. They are not encrypted and are not designed for concurrent writers in multiple processes. Keep them out of source control and protect them according to the sensitivity of the evaluated data.

## Budget controls

The library exposes three distinct budget behaviors. They serve different purposes and should not be treated as interchangeable.

### Post-run assessment

`assess_run_budget()` evaluates measured cost, token usage, and latency recorded in a completed run using `RunBudgetPolicy`. Missing required measurements produce incomplete evidence instead of being counted as zero.

### Observed-usage scheduling guard

`run_budgeted()` on the synchronous or asynchronous runner observes measured usage and stops scheduling additional work when the configured threshold is reached or required evidence is missing. An already-sent request or an in-flight batch may still incur charges before the guard can react.

### Reservation-based execution

For adapters and graders that can enforce a per-request ceiling, `run_reserved_budgeted()` reserves a per-case cost envelope before dispatch and accounts for outstanding reservations, including paid graders.

~~~python
from ai_eval_engineering import ReservedBudgetPolicy

result = runner.run_reserved_budgeted(
    suite,
    manifest,
    policy=ReservedBudgetPolicy(
        max_total_cost_usd=2.50,
        max_case_cost_usd=0.50,
    ),
)

print(result.status)
print(result.known_cost_usd)
print(result.reserved_cost_usd)
print(result.pending_case_ids)
print(result.incomplete_case_ids)
print(result.unresolved_cost_case_ids)
~~~

Strict reservation mode requires the adapter to implement `run_with_budget(..., max_cost_usd=...)` and every billable grader to implement `grade_with_budget(..., max_cost_usd=...)`. Those components must enforce the supplied allowance before sending billable requests and report actual charges accurately. The library cannot force an arbitrary third-party API or delayed billing system to honor a limit; configure provider-side hard spend limits as an additional safeguard where available.

See [Limitations](docs/limitations.md) for the precise semantics of incomplete usage evidence, in-flight work, and cost reporting.

## Failure-aware execution reports

The ordinary `run()` methods remain fail-fast. Use `run_report()` when a batch should continue after an individual adapter, output-validation, or grader failure and record each outcome without turning the failure into an artificial zero score.

~~~python
report = runner.run_report(
    suite,
    manifest,
    checkpoint_path="artifacts/evaluation-checkpoint.json",
)

print(report.completed_count)
print(report.failed_count)
print(report.is_complete)

for item in report.cases:
    if not item.completed:
        stage = item.failure.stage if item.failure is not None else "unknown"
        print(item.case.id, item.status, stage)
~~~

Reports preserve original suite order and can retain a validated system output plus earlier valid grader results when a later grader fails. Only fully completed cases are checkpointed, so failed cases can be attempted again when resuming. Cancellation and checkpoint I/O failures propagate instead of being recorded as ordinary per-case outcomes.

A partial execution report cannot be converted into an ordinary `EvaluationRun`. This prevents missing evaluation evidence from silently entering release-gate comparisons. Exception messages can include provider details or user data; review and redact reports before storing or sharing them.

## Comparisons and release policies

### Paired release evaluation

`evaluate_release_candidate()` compares recorded baseline and candidate runs on matching case IDs and case definitions. It evaluates configured numeric grader metrics and calculates paired-bootstrap confidence intervals, rather than treating matched cases as independent samples.

~~~python
from ai_eval_engineering import ReleaseMetricPolicy, evaluate_release_candidate

decision = evaluate_release_candidate(
    baseline_run,
    candidate_run,
    [
        ReleaseMetricPolicy(
            "task_success",
            direction="higher_is_better",
            max_allowed_regression=0.01,
            min_cases=30,
        ),
        ReleaseMetricPolicy(
            "latency_ms",
            direction="lower_is_better",
            max_allowed_regression=25.0,
            min_cases=30,
        ),
    ],
    confidence=0.95,
    resamples=2000,
    seed=7,
)

print(decision.status)  # PASS / FAIL / INCONCLUSIVE / INVALID_EVIDENCE
print(decision.summary())
~~~

A `PASS` means every configured metric's interval satisfies its allowed-regression tolerance on the evaluated cases. `FAIL` means at least one metric is beyond its tolerance; `INCONCLUSIVE` indicates unresolved uncertainty or insufficient sample size; `INVALID_EVIDENCE` means the runs cannot be compared safely.

For multiple metrics, the release gate applies a Bonferroni adjustment to the requested confidence level. Bootstrap intervals remain approximate, and a passing result is not a production-wide quality guarantee, formal power analysis, or proof of causal impact.

### Reproducible multi-metric policies

A versioned `release-policy-v1` file stores metric names, directions, regression tolerances, minimum case counts, confidence, bootstrap resamples, and a seed. The `ai-eval compare --policy` mode applies the policy without ad-hoc CLI overrides and includes the policy payload in its JSON decision for traceability.

The repository includes an example policy: [quality, latency, and safety](examples/policies/quality-latency-safety-v1.json).

### Failure-delta triage

`compare_failure_runs()` classifies failures between two compatible runs as new, resolved, or persistent. It rejects comparisons where the suite version, case definitions, case IDs, or per-case grader sets differ. A failure is resolved only when the corresponding grader ran and passed in the candidate.

### Offline slice analysis

`analyze_run_slices()` and `ai-eval slices` summarize results by case tags, risk categories, or a caller-selected scalar field in case metadata. Results include case counts and per-grader breakdowns so an overall score does not completely hide a concentrated failure pattern.

Slice summaries are descriptive. They do not automatically provide subgroup confidence intervals, correct for multiple comparisons across slices, or establish fairness. Tag slices may overlap, and metadata may contain sensitive values.

## Command-line interface

The `ai-eval` CLI works with recorded JSON files and does not make provider calls.

~~~bash
# Inspect commands
ai-eval --help

# Print versioned schemas
ai-eval schema
ai-eval suite-schema
ai-eval release-policy-schema

# Validate stored evidence
ai-eval validate-run external-results/candidate-run.json
ai-eval validate-suite examples/suites/support-smoke-v1.json

# Compare one numeric metric
ai-eval compare baseline.json candidate.json   --metric quality   --direction higher_is_better   --max-allowed-regression 0.02   --min-cases 30

# Compare multiple metrics using a versioned policy
ai-eval compare baseline.json candidate.json   --policy examples/policies/quality-latency-safety-v1.json

# Assess recorded cost, tokens, and latency
ai-eval budget candidate.json   --max-total-cost-usd 2.50   --max-total-tokens 50000   --max-case-latency-ms 15000
~~~

The CLI emits machine-readable JSON for decision commands. `compare` returns exit code `0` only for `PASS`; `FAIL`, `INCONCLUSIVE`, and `INVALID_EVIDENCE` return `1`. The `budget` command returns `1` when the budget is exceeded or its evidence is incomplete or invalid. Invalid input or configuration returns `2`.

For exact arguments and option defaults, use `ai-eval --help`.

## LLM-as-a-judge

The optional OpenAI-compatible judge uses the OpenAI Python SDK and Chat Completions Structured Outputs to request rubric-constrained results. The judge can be used directly or wrapped as a grader for an evaluation runner. The async variant supports native asynchronous execution.

~~~python
from ai_eval_engineering import (
    EvaluationRubric,
    OpenAICompatibleJudge,
    OpenAIJudgeGrader,
    RubricDimension,
)

rubric = EvaluationRubric(
    "answer-quality",
    (
        RubricDimension("correctness", "Matches the verified answer.", weight=0.7),
        RubricDimension("clarity", "Is concise and understandable.", weight=0.3),
    ),
)

judge = OpenAICompatibleJudge(
    model="gpt-4o-mini",
    temperature=0.0,
    timeout=30.0,
    max_retries=2,
)
grader = OpenAIJudgeGrader(
    judge,
    rubric,
    name="llm_quality",
    pass_labels=("pass", "passed"),
)

result = grader.grade(case, output)
print(result.passed, result.score, result.metadata.get("usage"))
~~~

Set `OPENAI_API_KEY` in the environment before making live calls. The adapter requires a model or endpoint that supports JSON Schema Structured Outputs; a custom OpenAI-compatible endpoint can be supplied through `base_url` or an injected client.

The pass flag is controlled by the explicitly configured `pass_labels`; it is not inferred from a high numeric score. Live judge calls can incur charges and send the case input, expected value, model output, and trace to the configured provider. Review that data for sensitive information. The CI suite uses deterministic fixtures and fake clients; it does not validate the quality of a particular live judge model.

The [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat) describes the provider-side response format.

### Judge calibration

`calibrate_judge()` compares model-judge labels with supplied human labels and reports per-label precision, recall, F1, balanced accuracy, macro metrics, a confusion matrix, and Cohen's kappa. A judge is an evaluator, not ground truth; calibration results depend on the supplied sample and label definitions.

## Agent, security, online, and trade-off evaluation

### Agent trajectories and security regressions

The `Trajectory` model validates ordered agent events so task-level success can be analyzed separately from step success, safety, and efficiency. Risk-tagged adversarial cases can be run through the same evaluation pipeline as ordinary cases.

The committed security fixtures demonstrate regression mechanics; they are intentionally small and are not a comprehensive security benchmark.

### Online-evaluation primitives

The package includes typed exposure and outcome records, metric contracts, A/B comparison utilities, and evidence guardrails for concerns such as missing outcomes, small samples, overlapping assignments, missing ground truth, and selection bias. These are building blocks—not a deployed experimentation service or production analytics integration.

A/B variants are treated as independent samples rather than paired observations when the experiment design assigns different users to different variants.

### Quality/cost and quality/latency trade-offs

Recorded cost and latency can be combined with quality observations to identify non-dominated trade-off frontiers. The library exposes the trade-off; it does not automatically decide which system is best. That choice depends on the application's constraints and priorities.

## Integrations

The repository contains contract-level adapters for three related projects:

- [Building Software With LLMs](https://github.com/peymanpro/Building-Software-With-LLMs)
- [Evidence-Grounded-RAG](https://github.com/peymanpro/Evidence-Grounded-RAG)
- [How Agents Work](https://github.com/peymanpro/How-Agents-Work)

The integrations use deterministic snapshots of documented behavior to verify adapter compatibility without importing those projects as runtime dependencies or launching their live processes in CI.

[Pretrained LLM Adaptation](https://github.com/peymanpro/Pretrained-LLM-Adaptation) is complementary: that project focuses on reproducible model adaptation and training evaluation, while this library focuses on reusable evaluation contracts, grading, statistical comparison, and release decisions. The evaluation framework does not automatically launch the adaptation benchmark.

## Evidence and methodology

Case-level observations are preserved before aggregation. A completed run can be exported as a machine-readable record or materialized into an evidence package using `write_evidence_package()`.

For implementation details, rationale, and documented boundaries, see:

- [Architecture](docs/architecture.md)
- [Evaluation methodology](docs/methodology.md)
- [Limitations and non-goals](docs/limitations.md)
- [Capability roadmap](docs/capability-roadmap.md)
- [V1.1 closure and evidence boundary](docs/V1.1-CLOSURE.md)
- [Changelog](CHANGELOG.md)

A useful evaluation record should identify its suite version, system version, configuration, seed when meaningful, environment, metric definitions, and uncertainty where applicable. A score without that context is difficult to reproduce or interpret.

## Limitations and non-goals

- **Fixtures are not production benchmarks.** Synthetic adapters and deterministic contract snapshots establish reproducible behavior of the examples, not the quality of a deployed model.
- **An LLM judge is not ground truth.** Use representative human labels and calibration when judge quality matters.
- **Budget controls have different guarantees.** Post-run assessment cannot stop a request; an observed-usage guard may react only after work has already incurred cost; reservation-based execution depends on adapter and grader enforcement. Use provider-side limits when available.
- **Slice analysis is descriptive.** It does not automatically establish subgroup significance or fairness and does not correct for multiple comparisons across slices.
- **Regex is not a sandbox.** Python's regular-expression engine has no built-in execution deadline; use trusted patterns.
- **Security coverage is limited.** The included adversarial taxonomy and fixtures are useful regression seeds, not comprehensive assurance.
- **Online primitives are not a hosted experimentation platform.** Live analytics and production experiment infrastructure remain outside the current scope.
- **External integrations are contract-level.** CI checks documented adapter behavior using deterministic snapshots rather than running each sibling application live.

See [docs/limitations.md](docs/limitations.md) for detailed behavior and caveats.

## Development

Install the development dependencies and run the same quality checks used in CI:

~~~bash
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src
~~~

The examples use synthetic or deterministic fixtures unless stated otherwise. CI includes schema checks, CLI checks, and examples for budget control, online-evaluation primitives, security regressions, trade-offs, integrations, Promptfoo interchange, asynchronous evaluation, deterministic graders, retries, structured/composite graders, and failure-aware reports. CI does not need a provider API key and makes no paid model calls.

Generated `artifacts/` files are ignored by Git. Do not commit run outputs that contain customer data, prompts, model outputs, traces, or other sensitive evaluation material.

## Release status

The `v0.3.0` GitHub Release is published with its built distributions. **The initial PyPI upload has not yet been completed.** The intended PyPI project page is [ai-evaluation-engineering](https://pypi.org/project/ai-evaluation-engineering/). The older `v0.2.0` release points to an earlier source revision and should not be treated as the distribution of the current `main` capabilities.

The release workflow validates the source, builds and checks the distributions, verifies wheel installation, and creates the matching GitHub Release. After the automatic-publishing workflow change is merged, a push to `main` will also publish to PyPI **when `pyproject.toml` contains a new version whose matching tag does not already exist**. Commits that keep the current version are deliberately skipped; a published PyPI version cannot be overwritten. Bump the project version for each release.

The manual `workflow_dispatch` option with `publish_pypi=true` remains available for the initial `0.3.0` upload and an explicit retry. PyPI Trusted Publishing must match owner `peymanpro`, repository `AI-Evaluation-Engineering`, workflow `release.yml`, and environment `pypi`. Until the first PyPI upload is confirmed, follow the source-install instructions above.
