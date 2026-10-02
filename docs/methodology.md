# Evaluation Methodology

## Deterministic grading

Use exact-match, schema, rule-based, and trajectory graders whenever expected behavior can be expressed without subjective interpretation.

## Model-based grading

A judge model is an evaluator, not ground truth. The repository exposes a provider-neutral judge boundary and a calibration workflow that compares judge labels against human labels.

## Statistical comparison

Case-level observations are preserved before aggregation. Bootstrap confidence intervals quantify uncertainty around selected metrics. Paired comparison requires identical population size and reports mean difference plus a standardized effect.

## Regression gates

A baseline is explicit: suite version, system version, and metric values. Release rules define the maximum acceptable drop. The gate fails when the candidate crosses that threshold.

## Scope

V1.0 is a reusable evaluation core with deterministic fixtures. Real cloud-model integration, online experimentation, adversarial benchmark expansion, and production analytics adapters remain future phases.
