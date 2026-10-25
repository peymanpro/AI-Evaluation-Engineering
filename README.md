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

## Agent and security evaluation

V1.1 adds a typed trajectory schema with replay validation and separate task-success, step-success, safety, and efficiency signals.

The committed `data/adversarial.json` suite is intentionally compact and human-readable. It demonstrates how risk-tagged cases become executable regression tests.

The security fixtures are not a comprehensive security benchmark and make no production assurance claim.

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
