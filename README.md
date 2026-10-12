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

## Online evaluation

The online layer keeps exposure, outcome, variant, and segment identifiers separate. It provides a vendor-neutral A/B adapter, segment-level comparisons, and evidence guardrails that surface insufficient evidence instead of forcing a conclusion.

Run the deterministic example with `python examples/online_experiment.py`.

## Trade-off analysis

Evaluation runs already carry cost and latency at the `SystemOutput` level. `TradeoffObservation` exposes non-dominated quality/cost and quality/latency views.

The framework reports trade-offs rather than automatically selecting a single preferred system.

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

To publish the next version, increment `[project].version` in `pyproject.toml` and push to `main`, or push a matching `vMAJOR.MINOR.PATCH` tag. Existing version tags and releases are never overwritten.
