# AI Evaluation Engineering

A provider-neutral evaluation layer for systematically measuring, comparing, and regression-testing AI systems.

This repository treats evaluation as an engineering discipline rather than a final metric-reporting step.

## What the library provides

- typed evaluation cases, suites, run manifests, outputs, and grader results;
- versioned JSON suite files with strict import/export validation, reusable datasets, and a packaged schema;
- reusable synchronous and bounded-concurrency asynchronous evaluation runners with provider-neutral system adapters;
- preflight validation for unique case IDs, JSON-compatible evidence, matching suite manifests, outputs, and grader results;
- atomic, resumable checkpoints for synchronous and asynchronous runs, with suite and run-identity validation;
- post-run budget assessments for recorded cost, token usage, and per-case latency;
- offline slice analysis by case tag, risk category, or selected scalar metadata, with per-grader breakdowns;
- deterministic exact-match, schema, rule-based, and trajectory graders;
- typed agent trajectory replay and separate task/step success analysis;
- an adversarial taxonomy and executable security-regression cases;
- optional synchronous and native-async OpenAI-compatible structured-output LLM judges, rubric representation, and human calibration;
- bootstrap confidence intervals, paired comparison, effect-size reporting, and run-to-run variance analysis;
- explicit baselines and deterministic regression gates;
- quality/cost and quality/latency trade-off frontiers;
- machine-readable, human-readable, and auditable evidence packages;
- a provider-free CLI for validating recorded runs, comparing baseline/candidate revisions, and enforcing post-run budgets;
- integration adapters for three existing portfolio projects;
- CI quality gates with tests, Ruff, mypy, and reproducible demonstrations;
- versioned external-run JSON interchange and a Promptfoo v3 JSON adapter;
- decision-grade paired release gates and failure-delta triage between system versions;
- persistent failure memory and class-aware calibration metrics;
- installable Python distributions with PyPI Trusted Publishing support.

## Architecture

    AI System Under Test
            ↓
     Evaluation Adapter
            ↓
     Evaluation Runner
            ↓
          Graders
       ↙     ↓      ↘
    rules  schema  trajectory / judge
            ↓
    Statistical Analysis
            ↓
      Regression Gate
            ↓
      Evidence Package

The framework preserves raw case-level observations so aggregate claims can be inspected and reproduced.

## Quick start

    pip install -e ".[dev]"
    # For the optional live OpenAI-compatible LLM judge: pip install -e ".[dev,openai]"
    pytest
    ai-eval-demo
    python examples/security_regression.py
    python examples/tradeoffs.py
    python examples/integrations.py
    python examples/promptfoo_release_workflow.py
    python examples/async_evaluation.py

Generated `artifacts/` output is ignored by Git. The Promptfoo workflow demo uses committed,
synthetic fixtures and makes no external model calls.

## Command-line interface

The `ai-eval` command works with saved external-run-v1 JSON files and makes no provider calls.
It complements `ai-eval-demo`, which remains a deterministic example that generates a demo report.

```bash
# Inspect the available commands and print the packaged JSON Schema
ai-eval --help
ai-eval schema > external-run-v1.schema.json

# Validate a recorded run file
ai-eval validate-run run.json

# Compare a baseline and candidate using the grader's numeric score
ai-eval compare baseline.json candidate.json \
  --metric quality \
  --direction higher_is_better \
  --max-allowed-regression 0.02 \
  --min-cases 30

# Enforce recorded cost, token, and latency limits in CI
ai-eval budget candidate.json \
  --max-total-cost-usd 2.50 \
  --max-total-tokens 50000 \
  --max-case-latency-ms 15000
```

`compare` and `budget` print machine-readable JSON and return exit code `0` only for a passing
gate. `compare` returns `1` for `FAIL`, `INCONCLUSIVE`, or `INVALID_EVIDENCE`; `budget` returns `1`
for `BUDGET_EXCEEDED`, `INCOMPLETE_EVIDENCE`, or `INVALID_EVIDENCE`. Invalid input or configuration
returns `2`. The CLI uses the same Python APIs and versioned interchange schema as the library.

## Versioned evaluation suites

Keep test cases in a reusable, reviewable JSON file rather than rebuilding every suite in Python.
Version 1 suite files include a suite version and case IDs, inputs, expected values, tags, metadata,
and optional risk categories. The importer rejects unknown fields, unsupported schema versions,
duplicate case IDs, and invalid/non-finite JSON evidence.

The repository includes a small [suite JSON example](examples/suites/support-smoke-v1.json). Validate
it from the command line:

```bash
ai-eval validate-suite examples/suites/support-smoke-v1.json
ai-eval suite-schema > evaluation-suite-v1.schema.json
```

Load the same dataset from Python and pass it to either runner:

```python
from ai_eval_engineering import load_suite_json, write_suite_json

suite = load_suite_json("examples/suites/support-smoke-v1.json")
print(suite.version, len(suite.cases))

# Export a modified suite using an atomic file replacement.
write_suite_json(suite, "data/support-suite-v1.json")
```

The packaged schema can also be retrieved with `get_evaluation_suite_schema()`. A suite file defines
cases and evidence contracts, not the executable system adapter or graders; configure those in code
so loading data never executes arbitrary Python.

## Input contract validation

Both runners validate the suite and run manifest before making system calls. They reject duplicate
case IDs, empty identifiers, non-JSON values and non-finite numbers in case evidence, or a manifest
whose suite version does not match the cases being evaluated. Adapter outputs and grader results are
also checked before they enter the recorded run, including output IDs, finite cost/latency, and unique
grader names per case.

You can validate a dataset explicitly before scheduling model calls:

```python
from ai_eval_engineering import EvaluationSuite, validate_suite

suite = EvaluationSuite("support-v1", cases=...)
validate_suite(suite)
```

The runners invoke this check automatically. Contract validation catches structural inconsistencies;
it does not prove that the test cases, labels, graders, or model outputs are semantically correct.

## Asynchronous evaluation

Use `AsyncEvaluationRunner` when the system under test is accessed through async HTTP clients,
model APIs, or another asynchronous runtime. Set `max_concurrency` to cap in-flight system calls.
The runner preserves the original suite order in the returned `EvaluationRun`, even when requests
finish in a different order, and reuses the existing synchronous grader contract. An optional
`timeout_per_case_seconds` setting places a deadline on each async system call.

```python
import asyncio

from ai_eval_engineering import (
    AsyncEvaluationRunner,
    EvaluationCase,
    EvaluationSuite,
    SystemOutput,
)
from ai_eval_engineering.graders import ExactMatchGrader
from ai_eval_engineering.runner import build_run_metadata


class MyAsyncSystem:
    async def run(self, case: EvaluationCase) -> SystemOutput:
        response = await your_async_model_client(case.input)
        return SystemOutput(case_id=case.id, output=response)


async def main() -> None:
    suite = EvaluationSuite(
        "support-v1",
        (EvaluationCase("case-1", {"question": "Where is my order?"}, expected="shipped"),),
    )
    runner = AsyncEvaluationRunner(
        MyAsyncSystem(),
        [ExactMatchGrader()],
        max_concurrency=8,
        timeout_per_case_seconds=30.0,
    )
    run = await runner.run(
        suite,
        build_run_metadata(suite, "support-assistant", "git:abc123"),
    )
    print([(item.case.id, item.graders[0].passed) for item in run.cases])


asyncio.run(main())
```

The adapter's `run` method must be async and return a `SystemOutput`. Both synchronous and
asynchronous graders are accepted. Synchronous graders execute on the event loop, so keep them fast
and non-blocking; asynchronous graders are awaited. If an adapter or grader raises, pending worker
tasks are cancelled and the runner raises instead of returning a partial run. A timeout cancels the
current adapter coroutine and fails the run; it does not return a partial `EvaluationRun`. The async
runner does not silently retry requests because retry safety and rate limits are provider-specific.
See the [async demo](examples/async_evaluation.py).

### Asynchronous LLM judge

For model-based grading, `AsyncOpenAICompatibleJudge` uses the SDK's native `AsyncOpenAI` client,
and `AsyncOpenAIJudgeGrader` adapts it to the async runner. Install the optional extra with
`pip install "ai-evaluation-engineering[openai]"`. The request uses the same JSON Schema structured
output contract, evidence serialization, rubric validation, and explicit label-to-pass mapping as
the synchronous judge. No API call is made until `await grader.grade(...)` or an async run executes.

```python
from ai_eval_engineering import AsyncOpenAICompatibleJudge, AsyncOpenAIJudgeGrader

# The OpenAI SDK reads OPENAI_API_KEY from the environment by default.
judge = AsyncOpenAICompatibleJudge(
    model="your-model",
    timeout=30.0,
    max_retries=2,
)
judge_grader = AsyncOpenAIJudgeGrader(
    judge,
    rubric,
    name="quality_judge",
    pass_labels=("pass", "passed"),
)
runner = AsyncEvaluationRunner(
    async_system,
    [judge_grader],
    max_concurrency=8,
    timeout_per_case_seconds=45.0,
)
run = await runner.run(suite, manifest)
```

The runner deadline covers the async system-adapter call; the judge's own `timeout` configures
its provider request. Choose the limits with your rate limits and latency budget in mind. CI tests
use a fake async client and make no live model calls; calibration against representative
human-labelled examples is still required.


## Resumable evaluation runs

Pass `checkpoint_path` to either runner to atomically persist each completed case and resume after
a later case fails. On resume, the runner verifies the complete suite fingerprint and the system,
version, configuration, seed, and environment recorded in the manifest. Completed cases are reused;
only unfinished cases execute again.

```python
runner = EvaluationRunner(async_or_sync_system, graders)
run = runner.run(
    suite,
    manifest,
    checkpoint_path=".local-runs/support-assistant.checkpoint.json",
)
```

For an async adapter, the call is awaited in the normal way:

```python
run = await AsyncEvaluationRunner(
    async_system,
    graders,
    max_concurrency=8,
    timeout_per_case_seconds=30.0,
).run(suite, manifest, checkpoint_path=".local-runs/support-assistant.checkpoint.json")
```

If a case raises, the run still raises instead of presenting partial evidence as complete, while the
checkpoint retains earlier successful cases. Re-running with the same suite, manifest identity, and
path resumes the unfinished cases. A completed checkpoint is also reused; choose a new path or
remove the old checkpoint to start a fresh evaluation. Incompatible or malformed checkpoints raise
`CheckpointError` and are never silently discarded.

Checkpoints contain the run manifest, case inputs, expected values, outputs, traces, and grader
details. They are written atomically but are not encrypted and are not designed for multiple
processes to write concurrently to the same path. Keep them out of source control and protect them
according to the sensitivity of the evaluated data.

## Run budget assessment

`RunBudgetPolicy` evaluates measured cost, token usage, and per-case latency against explicit
limits. Cost and latency come from `SystemOutput.cost_usd` and `SystemOutput.latency_ms`;
token usage is read from grader `metadata["usage"]` (the OpenAI-compatible judges record token
counts when the provider returns them).

```python
from ai_eval_engineering import RunBudgetPolicy, assess_run_budget

assessment = assess_run_budget(
    run,
    RunBudgetPolicy(
        max_total_cost_usd=2.50,
        max_case_cost_usd=0.50,
        max_total_tokens=50_000,
        max_case_latency_ms=15_000,
    ),
)

if not assessment.passed:
    print(assessment.status)
    print(assessment.violations)
    print(assessment.issues)
```

The status is one of `WITHIN_BUDGET`, `BUDGET_EXCEEDED`, `INCOMPLETE_EVIDENCE`, or
`INVALID_EVIDENCE`. Missing measurements are never counted as zero: when a configured limit needs
data that a case did not record, the result is incomplete unless a known measurement already proves
the budget was exceeded. Known token counts from multiple graders are summed per case.

This is a post-run budget assessment, not a live spend limiter: it cannot stop a request before a
provider charges for it. Costs are not inferred from token counts because provider/model pricing
varies; adapters must record the actual cost they can measure.

## Offline slice analysis

A single pass rate can hide a serious failure in a smaller or higher-risk group. Use
`analyze_run_slices` to break a completed run down by case tag, risk category, or one explicitly
selected top-level metadata field. Each slice reports its case count, all-graders pass rate, mean
case score, whether it meets the configured minimum case count, and per-grader pass rates/scores.

```python
from ai_eval_engineering import analyze_run_slices

for item in analyze_run_slices(run, by="risk_category", min_cases=30):
    print(
        item.value,
        item.case_count,
        item.pass_rate,
        item.meets_min_cases,
    )
    for grader in item.grader_metrics:
        print("  ", grader.grader, grader.pass_rate, grader.mean_score)
```

Select only the slice dimensions relevant to the evaluation policy. Metadata slicing supports
scalar values only; arbitrary nested objects are rejected rather than silently stringified. Missing
classifications appear as a `None` slice by default, and small slices are retained and flagged rather
than dropped. A case with multiple tags appears in each corresponding tag slice, so tag-slice counts
are not mutually exclusive.

The recorded-run CLI supports the same analysis without making provider calls:

```bash
ai-eval slices candidate.json --by risk_category --min-cases 30
ai-eval slices candidate.json --by metadata.locale --exclude-missing
```

These summaries are descriptive diagnostics, not statistical significance tests. A small slice is
not evidence of safety or quality; inspect the count and use a suitable inferential method before
making comparative claims. Since selected metadata values are included in output summaries, do not
slice on confidential or directly identifying metadata.

## Promptfoo adapter

Promptfoo v3 exports can be imported directly from the JSON file produced by
`promptfoo eval -o results.json`. The adapter normalizes one provider/prompt combination into an
`EvaluationRun`, preserving case variables and assertions, pass/fail score, grader reason,
latency, cost, named scores, and available error/trace identifiers.

```python
from ai_eval_engineering import load_promptfoo_json

run = load_promptfoo_json(
    "results.json",
    system_name="support-assistant",
    system_version="git:9f3ab21",
    suite_version="support-suite-v2",
    provider_id="openai:chat:example-model",
    prompt_idx=0,
)

print(run.manifest.run_id)
print(len(run.cases))
```

The system and suite versions are supplied by the caller so the release gate can compare the
intended revisions. Promptfoo exports that contain multiple providers or prompt indices must be
sliced explicitly with `provider_id` and/or `prompt_idx`; the adapter refuses ambiguous mixes.
For provider/runtime error rows without a model response, it retains the failed case with a null
output and the error reason rather than dropping it.

The initial adapter targets the documented Promptfoo v3 JSON envelope
(`results.version == 3`, with result rows in `results.results`). It does not yet import JSONL,
CSV, JUnit XML, Promptfoo v2 files, or red-team-specific exports. See the
[Promptfoo JSON output format](https://www.promptfoo.dev/docs/configuration/outputs/) and
[Promptfoo CI/CD JSON schema](https://www.promptfoo.dev/docs/integrations/ci-cd/) for the source
format.

Promptfoo JSON exports may contain raw model output, prompts, variables, configuration, and
other sensitive data. Review the source file and protect imported artifacts before committing or
sharing them.

## Promptfoo baseline vs candidate workflow

`examples/promptfoo_release_workflow.py` joins the Promptfoo adapter to both existing
comparison APIs: `evaluate_release_candidate` makes a paired-bootstrap release decision, and
`compare_failure_runs` identifies newly failing, resolved, and persistent case/grader pairs.

Run the deterministic CI demonstration:

```bash
python examples/promptfoo_release_workflow.py
```

The committed baseline/candidate files are **synthetic Promptfoo-v3-shaped fixtures**, not results
captured from a real model provider. They demonstrate a known regression so the tests can verify
that the release gate returns `FAIL` and that the failure delta reports 11 new, 2 resolved, and
4 persistent failures. No network or model calls occur.

To compare your own Promptfoo v3 exports:

```bash
python examples/promptfoo_release_workflow.py baseline.json candidate.json \
  --system-name support-assistant \
  --baseline-version git:abc123 \
  --candidate-version git:def456 \
  --suite-version support-suite-v2 \
  --provider-id 'openai:chat:example-model' \
  --prompt-idx 0 \
  --min-cases 30 \
  --max-allowed-regression 0.02 \
  --enforce-gate
```

The same `suite-version` must describe the same case definitions in both files. Choose the
`system-version` values yourself; provider and prompt identifiers are not sufficient to identify
a deployment revision. The release metric named `promptfoo` uses the row-level Promptfoo
`score`; named scores remain preserved in grader metadata and are not automatically registered as
separate release metrics.

By default, the example prints the decision without rejecting a candidate solely because the
decision is `FAIL` or `INCONCLUSIVE`. Add `--enforce-gate` in a CI/CD invocation to return
exit code 1 for those decisions. Invalid evidence or incompatible runs return exit code 2.
Without `--enforce-gate`, a valid `FAIL` or `INCONCLUSIVE` decision is printed but does not
reject the command; `INVALID_EVIDENCE` still returns exit code 2.

Example output from the committed synthetic fixtures (numeric values are deterministic for the
configured seed and bootstrap settings):

```text
Baseline:  model-v1 | 30 cases
Candidate: model-v2 | 30 cases

Release decision: FAIL
promptfoo: baseline=0.8000, candidate=0.5000, delta=-0.3000
95% CI=[-0.5000, -0.1000], n=30

failure delta: 11 new, 2 resolved, 4 persistent
```

The example scores and failure counts demonstrate plumbing and regression detection only; they are
not measured model performance. Review raw prompts, test variables, expected answers, outputs,
and generated reports for sensitive information before sharing exported files or reports.

## External evaluation result interchange

External tools can import their completed evaluations through a small, versioned JSON contract.
Map the tool's run metadata, test cases, observed outputs, and grader results into schema version
`1`; the importer validates IDs, required fields, numeric values, and JSON-compatible metadata
before constructing the same `EvaluationRun` objects used by the rest of this package.

```python
from ai_eval_engineering import load_run_json, write_run_json

# A normalized interchange file exported by an external evaluator:
candidate = load_run_json("external-results/candidate-run.json")

# Save a validated, canonical copy that another tool can consume:
write_run_json(candidate, "normalized/candidate-run.json")
print(candidate.manifest.system_version, len(candidate.cases))
```

The JSON envelope contains `schema_version`, `manifest`, and `cases`. Each case result contains a
`case` object, an `output` object, and a non-empty `graders` array. Case IDs and grader names
must be unique within their required scope; each output's case ID must match its case. Scores must
be finite numbers, and latency/cost must be finite and non-negative. Nested metadata and outputs
must contain JSON values only.

The versioned JSON Schema ships inside the installed wheel and can be loaded by consumers that
need to validate their own export files before handing them to the importer:

```python
from ai_eval_engineering import get_external_run_schema

schema = get_external_run_schema()
print(schema["$schema"])
print(schema["properties"]["schema_version"]["const"])
```

This is a provider-neutral interchange format, not a built-in SDK for a particular vendor. The
external tool or a small tool-specific adapter remains responsible for mapping its fields into the
documented envelope. Unknown schema versions fail explicitly instead of being guessed.

## Agent and security evaluation

V1.1 adds a typed trajectory schema with replay validation and separate task-success, step-success, safety, and efficiency signals.

The committed `data/adversarial.json` suite is intentionally compact and human-readable. It demonstrates how risk-tagged cases become executable regression tests.

The security fixtures are not a comprehensive security benchmark and make no production assurance claim.

## Failure delta between versions

After collecting failures from two runs, `compare_failure_runs` classifies them as new,
resolved, or persistent. It refuses comparisons across suite versions, changed test definitions,
changed case IDs, or different grader sets, so removing a grader cannot masquerade as fixing its
failures.

```python
from ai_eval_engineering import compare_failure_runs

delta = compare_failure_runs(baseline_run, candidate_run)
print(delta.summary())
print("New regressions:", delta.new_failure_count)
print("Resolved:", delta.resolved_failure_count)
print("Still failing:", delta.persistent_failure_count)

for failure in delta.new_failures:
    print(failure.case.id, failure.grader, failure.latest_details)

for failure in delta.persistent_failures:
    print(
        failure.candidate.case.id,
        failure.candidate.grader,
        failure.score_delta,  # raw candidate score minus baseline score
    )
```

A persistent failure's score delta is descriptive only; whether a score increase is an improvement
depends on the grader's definition. A failure is classified as resolved only when the corresponding
grader ran and passed in the candidate. Both runs must use the same system name, suite version,
case definitions, and per-case grader set.

## OpenAI-compatible LLM judge

The core package now includes an optional, real model-backed judge adapter. It uses the OpenAI
Python SDK with Chat Completions Structured Outputs, validates every returned field against the
rubric, and records provider/model/request/token-usage metadata without storing the raw API
response. The base installation remains dependency-free; install the optional SDK extra when
you need a live provider call.

```bash
pip install "ai-evaluation-engineering[openai]"
```

Set `OPENAI_API_KEY` in your environment, then use the judge directly or wrap it as a grader for
`EvaluationRunner`:

```python
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

# case and output are EvaluationCase and SystemOutput instances
result = grader.grade(case, output)
print(result.passed, result.score, result.details)
print(result.metadata.get("usage"))
```

The grader does not infer success from a high score alone: `passed` is true only when the label
matches the explicitly configured `pass_labels`. The numeric score is retained separately for
analysis and release gates. The adapter requires an endpoint/model that supports JSON Schema
Structured Outputs; a custom OpenAI-compatible endpoint can be supplied via `base_url` or an
injected client. See the [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat).

Live judge calls send the case input, expected value, model output, and trace to the configured
provider and can incur API charges. Review those fields for sensitive data. CI tests use an
injected fake client and make no provider calls, so a green test suite validates integration
mechanics, not the quality of a particular model judge.

## Judge calibration

A judge that agrees with a majority class can still miss a minority class. `calibrate_judge`
therefore reports per-label precision/recall/F1 in addition to raw agreement, balanced accuracy,
macro metrics, a confusion matrix, and Cohen's kappa. Input maps must cover exactly the unique
calibration case IDs; malformed or duplicate inputs fail explicitly rather than being silently
ignored.

```python
from ai_eval_engineering import (
    EvaluationRubric,
    FakeJudge,
    RubricDimension,
    calibrate_judge,
)

cases = [case_a, case_b, case_c]
outputs = {case.id: output_by_id[case.id] for case in cases}
human_labels = {"case-a": "pass", "case-b": "fail", "case-c": "pass"}

report = calibrate_judge(
    cases,
    FakeJudge({"case-a": ("pass", 0.9), "case-b": ("pass", 0.8), "case-c": ("pass", 0.95)}),
    outputs,
    human_labels,
    EvaluationRubric(
        "answer-quality",
        (RubricDimension("correctness", "Matches the verified expected answer"),),
    ),
)

print(report.agreement_rate)
print(report.balanced_accuracy)
print(report.per_label_metrics["fail"].recall)
print(report.cohen_kappa)
```

Undefined precision is represented as `None` when a label is never predicted; macro precision
treats that undefined value as zero for reference labels. Cohen's kappa is `None` when its
expected-agreement denominator is zero. Calibration metrics measure agreement with the supplied
human labels—they do not establish that those labels are correct or that a judge is fair on
unobserved populations.

## Failure-to-regression memory

A failed grader/case pair can be captured as a stable regression-memory record, merged across
runs, saved to JSONL, and rebuilt into a small regression suite. Repeated failures keep their
history by run ID; the record identity remains stable across system versions when the versioned
suite, test definition, and grader name remain unchanged.

```python
from pathlib import Path

from ai_eval_engineering import (
    build_failure_regression_suite,
    extract_failure_records,
    merge_failure_memory,
    read_failure_memory,
    write_failure_memory,
)

memory_path = Path("failure-memory.jsonl")
existing = read_failure_memory(memory_path) if memory_path.exists() else ()
observed = extract_failure_records(completed_run)
memory = merge_failure_memory(existing, observed)
write_failure_memory(memory, memory_path)

regression_suite = build_failure_regression_suite(
    memory,
    version="regression-v1",
)
print(f"Known failure records: {len(memory)}")
print(f"Unique regression cases: {len(regression_suite.cases)}")
```

The JSONL record stores the case input, expected value, metadata, grader score/details, and
run history, but deliberately omits the observed model output by default. Input prompts, expected
values, metadata, and grader details can still contain sensitive information; inspect or redact
them before writing the memory file. The generated suite deduplicates identical cases and rejects
conflicting definitions that reuse the same case ID.

## Decision-grade release evaluation

Use `evaluate_release_candidate` when you need more than a threshold-only regression check.
It compares recorded baseline and candidate runs on the same versioned suite, requires the same
case IDs and case definitions, aligns each grader score by case ID, and uses a paired bootstrap
interval to avoid treating matched cases as independent samples.

```python
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
```

The release status is conservative: `PASS` means every configured metric's paired-bootstrap
interval stays within its allowed-regression tolerance on these evaluated cases; `FAIL` means
at least one metric's interval is beyond its tolerance; `INCONCLUSIVE` means the result overlaps
a tolerance boundary or the configured minimum case count is not met; `INVALID_EVIDENCE` means
the runs could not be compared safely (for example, a suite/version mismatch, changed case inputs,
unmatched case IDs, or missing metric results).

When several metric policies are evaluated together, the engine applies a Bonferroni adjustment to the requested confidence level across those metrics. This is conservative; because the intervals use a percentile bootstrap, coverage remains approximate rather than a formal guarantee.

A `PASS` is not a production-wide quality guarantee, a formal power analysis, or proof of causal
impact. It depends on the supplied evaluation cases, score semantics, confidence level, and
paired-bootstrap assumptions. The metric name must identify a numeric grader score recorded for
every case in both runs.

## Direction-aware regression gates

Release-gate rules can explicitly state whether a metric should increase or decrease. The default
`higher_is_better` direction preserves the existing API behavior for metrics such as task success
or quality scores; use `lower_is_better` for metrics such as cost, latency, or failure rate.

```python
from ai_eval_engineering.regression import (
    BaselineRecord,
    RegressionRule,
    evaluate_gate,
)

baseline = BaselineRecord(
    suite_version="suite-v1",
    system_version="model-v1",
    metrics={"task_success": 0.91, "latency_ms": 420.0},
)

result = evaluate_gate(
    baseline,
    {"task_success": 0.90, "latency_ms": 390.0},
    [
        RegressionRule("task_success", max_allowed_drop=0.02),
        RegressionRule(
            "latency_ms",
            max_allowed_drop=50.0,
            direction="lower_is_better",
        ),
    ],
)
assert result.passed
```

Metric values and regression tolerances must be finite numbers; tolerances must be non-negative.
This gate checks the configured metric thresholds only. It does **not** establish statistical
significance, verify that the current run used the same suite version, or prove overall production
quality. Those concerns require a decision-grade release policy with explicit run metadata and
uncertainty analysis.

## Online evaluation

The online layer keeps exposure, outcome, variant, and segment identifiers separate. It provides a vendor-neutral A/B adapter, segment-level comparisons, and evidence guardrails that surface insufficient evidence instead of forcing a conclusion.

Run the deterministic example with `python examples/online_experiment.py`.

## Trade-off analysis

Evaluation runs already carry cost and latency at the `SystemOutput` level. `TradeoffObservation` exposes non-dominated quality/cost and quality/latency views.

The framework reports trade-offs rather than automatically selecting a single preferred system.

The online evidence assessment checks configured data-integrity rules and minimum sample counts. A `sufficient` state does not prove statistical power, causal validity, or practical significance. Comparisons with fewer than two observations in either group retain their descriptive difference but do not report a bootstrap confidence interval; the interval is `None`, not zero uncertainty.


## Integration boundary

The repository includes provider-neutral adapters for:

- [Building Software With LLMs](https://github.com/peymanpro/Building-Software-With-LLMs);
- [Evidence-Grounded-RAG](https://github.com/peymanpro/Evidence-Grounded-RAG);
- [How Agents Work](https://github.com/peymanpro/How-Agents-Work).

These are **contract-level integrations** built from deterministic snapshots of documented behavior, not claims of live-process or network integration. This keeps the evaluation package network-independent and reproducible while making interface expectations testable. The adapters can later be replaced with live-process adapters when a real runtime is available.
## Model adaptation and evaluation

[Pretrained LLM Adaptation](https://github.com/peymanpro/Pretrained-LLM-Adaptation) is a complementary project focused on a reproducible LoRA/PEFT training and evaluation workflow. This repository focuses on reusable evaluation contracts, graders, statistical comparisons, and regression gates.

The distinction matters:

~~~text
Pretrained model + dataset
          ↓
training / adaptation
          ↓
held-out metrics + predictions
          ↓
versioned evaluation cases and graders
          ↓
comparison / regression decision
~~~

The repositories are independently runnable. This evaluation framework does **not** automatically launch the adaptation benchmark, and a training-time score by itself is not a substitute for a separately versioned evaluation suite.
## Evidence policy

This repository does not treat a small synthetic, deterministic, or contract-snapshot benchmark as a production quality claim.

Every reported evaluation should identify:

- dataset or suite version;
- system or model version;
- configuration;
- seed when meaningful;
- environment;
- metric definition;
- uncertainty where applicable;
- known limitations.

## Current scope boundary

This repository provides offline evaluation, deterministic comparison, release-gate logic, failure
deltas, and vendor-neutral Promptfoo result import. It also includes online-evaluation primitives
and examples, but it is not a deployed experimentation platform. Live cloud-provider integrations
and production analytics adapters remain outside the current scope. The Promptfoo CI demonstration
uses synthetic fixtures; real provider output is only evaluated when the caller supplies real JSON
exports.

See `docs/architecture.md`, `docs/methodology.md`, `docs/limitations.md`, and `docs/V1.1-CLOSURE.md`.

## Install from PyPI

**PyPI publication is intentionally deferred until the library's capabilities are complete.** The current `v0.2.0` is available as a GitHub Release, but do not assume the PyPI package is installable yet. When the package is published at the end of feature development, the normal installation will be:

```bash
pip install ai-evaluation-engineering
```

For the optional live OpenAI-compatible judge, install its extra:

```bash
pip install "ai-evaluation-engineering[openai]"
```

If the package has not yet been published on PyPI, the release workflow or trusted-publisher setup is still pending; do not assume a successful GitHub Release alone means a PyPI upload succeeded.

## Automated releases and PyPI publishing

The release workflow validates the source, runs the test suite, Ruff, mypy, and the project's core,
online-evaluation, security-regression, trade-off, integration-contract, and Promptfoo baseline/candidate
demonstrations. It then builds and validates the wheel and source distribution, smoke-tests the built
wheel, and attaches the validated distributions to the GitHub Release.

**PyPI publishing is deliberately disabled for normal pushes, tag pushes, and automatic release runs.**
This project is still in feature development; a successful CI run or GitHub Release does not publish
the package to PyPI. When the feature set is ready, an authorized maintainer must manually run the
`Release` workflow from `main` and explicitly set `publish_pypi=true` with the matching
`version`. The workflow then validates the versioned source and publishes the corresponding
validated distributions using [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/);
no long-lived PyPI token is stored by the workflow.

Before that final publication, configure a Trusted Publisher (or a pending publisher if the project
does not yet exist) in the PyPI account. Use owner `peymanpro`, repository
`AI-Evaluation-Engineering`, workflow file `.github/workflows/release.yml`, and GitHub environment
`pypi`. See the [PyPI setup guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
This account-level configuration is intentionally separate from feature development.

Existing version tags are never overwritten. CI uses synthetic Promptfoo fixtures and makes no paid
model calls. A GitHub Release is not evidence that the package has been published on PyPI.
