# AI Evaluation Engineering

A provider-neutral evaluation layer for systematically measuring, comparing, and regression-testing AI systems.

This repository treats evaluation as an engineering discipline rather than a final metric-reporting step.

## What V1.1 demonstrates

- typed evaluation cases, suites, run manifests, outputs, and grader results;
- reusable evaluation runners with provider-neutral system adapters;
- deterministic exact-match, schema, rule-based, and trajectory graders;
- typed agent trajectory replay and separate task/step success analysis;
- an adversarial taxonomy and executable security-regression cases;
- a model-judge boundary with rubric representation and human calibration;
- bootstrap confidence intervals, paired comparison, effect-size reporting, and run-to-run variance analysis;
- explicit baselines and deterministic regression gates;
- quality/cost and quality/latency trade-off frontiers;
- machine-readable, human-readable, and auditable evidence packages;
- integration adapters for three existing portfolio projects;
- CI quality gates with tests, Ruff, mypy, and reproducible demonstrations.

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
    pytest
    ai-eval-demo
    python examples/security_regression.py
    python examples/tradeoffs.py
    python examples/integrations.py

Generated `artifacts/` output is ignored by Git.

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
  --max-allowed-regression 0.02
```

The same `suite-version` must describe the same case definitions in both files. Choose the
`system-version` values yourself; provider and prompt identifiers are not sufficient to identify
a deployment revision. The release metric named `promptfoo` uses the row-level Promptfoo
`score`; named scores remain preserved in grader metadata and are not automatically registered as
separate release metrics.

By default, the example prints the decision without rejecting a candidate solely because the
decision is `FAIL` or `INCONCLUSIVE`. Add `--enforce-gate` in a CI/CD invocation to return
exit code 1 for those decisions. Invalid evidence or incompatible runs return exit code 2. Review
raw prompts, test variables, expected answers, and outputs for sensitive information before
sharing exported JSON files or their generated reports.

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

## V1.1 boundary

The completed portfolio scope intentionally stops before online experimentation, cloud-provider integration, and production analytics adapters.

See `docs/architecture.md`, `docs/methodology.md`, `docs/limitations.md`, and `docs/V1.1-CLOSURE.md`.

## Automated releases

The release workflow reads the version from `pyproject.toml`, runs the test suite, Ruff, mypy, and the project's core, online-evaluation, security-regression, trade-off, and integration-contract demonstrations. It then builds the Python distributions and attaches them to the GitHub Release with generated release notes.

To publish the next version, increment `[project].version` in `pyproject.toml` and push to `main`, or push a matching `vMAJOR.MINOR.PATCH` tag. Existing version tags and releases are never overwritten. The wheel and source distribution are attached only after the CLI, evaluation, security-regression, trade-off, and integration-contract demonstrations complete successfully. Those integration adapters are deterministic contract snapshots rather than live-process integration claims.
