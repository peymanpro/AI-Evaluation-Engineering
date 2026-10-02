# AI Evaluation Engineering

A provider-neutral evaluation layer for systematically measuring, comparing, and regression-testing AI systems.

This repository treats evaluation as an engineering discipline rather than a final metric-reporting step.

## What V1.0 demonstrates

- typed evaluation cases, suites, run manifests, outputs, and grader results;
- reusable evaluation runners with provider-neutral system adapters;
- deterministic exact-match, schema, rule-based, and trajectory graders;
- a model-judge boundary with rubric representation and human calibration;
- bootstrap confidence intervals, paired comparison, effect-size reporting, and run-to-run variance analysis;
- explicit baselines and deterministic regression gates;
- machine-readable and human-readable evidence reports;
- CI quality gates with tests, Ruff, mypy, and a reproducible demo.

## Architecture

    AI System Under Test
            ↓
     Evaluation Adapter
            ↓
     Evaluation Runner
            ↓
          Graders
       ↙     ↓      ↘
    rules  schema  trajectory / judge boundary
            ↓
    Statistical Analysis
            ↓
      Regression Gate
            ↓
       Evidence Report

The framework preserves raw case-level observations so aggregate claims can be inspected and reproduced.

## Quick start

    pip install -e ".[dev]"
    pytest
    ai-eval-demo

The demo writes artifacts/demo-report.json and artifacts/demo-report.md.

## Evidence policy

This repository does not treat a small synthetic or deterministic benchmark as a production quality claim.

Every reported evaluation should identify:

- dataset or suite version;
- system or model version;
- configuration;
- seed when meaningful;
- environment;
- metric definition;
- uncertainty where applicable;
- known limitations.

## V1.0 boundary

The implemented core intentionally stops before online experimentation, adversarial benchmark expansion, cloud-provider integration, and production analytics. Those are planned extensions rather than implied capabilities.

See docs/architecture.md and docs/methodology.md for the design and evaluation method.
