# Architecture

The V1.1 evaluation path is:

System Under Test → Evaluation Adapter → Case Execution → Graders → Statistical Analysis → Regression Gate → Evidence Package.

The framework separates case definition from execution, grading, statistical interpretation, reporting, and release gating.

## Agent path

Raw trace dictionaries can be normalized into the sequence:
action → observation → state transition → tool result → termination

The Trajectory object validates event ordering and provides a replayable representation.

## Security path

Risk-tagged adversarial cases enter the same suite/runner pipeline. Security-specific reporting is a taxonomy layer, not a separate evaluation engine.

## Trade-off path

A run can attach cost_usd and latency_ms to system outputs. Trade-off observations can then be projected onto non-dominated quality/cost and quality/latency views.

## Integration path

A sibling project is represented by a small ContractAdapter. The core knows only its output contract and integration metadata; it does not import project-specific internals.

## Evidence path

A completed run can be materialized as:
manifest.json + raw-results.json + configuration.json + report.json + report.md

This package is suitable for later audit without storing large external artifacts in source control.
