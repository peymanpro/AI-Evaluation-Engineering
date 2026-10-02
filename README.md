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

- `peymanpro/Building-Software-With-LLMs`;
- `peymanpro/Evidence-Grounded-RAG`;
- `peymanpro/HowAgentsWork`.

The CI demonstrations use deterministic contract snapshots derived from documented behavior. This keeps the core package network-independent and reproducible. The adapters can later be replaced with live-process adapters when a real runtime is available.

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
