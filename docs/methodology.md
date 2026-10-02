# Evaluation Methodology

## Deterministic grading

Use exact-match, schema, rule-based, and trajectory graders whenever expected behavior can be expressed without subjective interpretation.

## Model-based grading

A judge model is an evaluator, not ground truth. The repository exposes a provider-neutral judge boundary and a calibration workflow that compares judge labels against human labels.

## Statistical comparison

Case-level observations are preserved before aggregation. Bootstrap confidence intervals quantify uncertainty around selected metrics. Paired comparison requires identical population size and reports mean difference plus a standardized effect.

## Agent evaluation

Agent traces are normalized into typed events. Task success, step success, safety, and efficiency are reported separately so a successful task does not hide an unsafe or inefficient trajectory.

## Adversarial evaluation

Security cases carry explicit risk categories and are treated as regression-test inputs. The committed taxonomy is intentionally small and does not claim comprehensive coverage.

## Trade-off analysis

Quality/cost and quality/latency views expose non-dominated variants. The reporting layer does not choose a single winner automatically.

## Integration methodology

Sibling repositories are adapted through provider-neutral contracts. CI uses deterministic contract snapshots so the evaluation framework remains reproducible and independent of external network/service availability.

## Reporting and evidence

Reports preserve manifest, case-level observations, summary metrics, uncertainty, regression results, and failure taxonomy. Evidence packages materialize these inputs in an auditable directory.

## Regression gates

A baseline is explicit: suite version, system version, and metric values. Release rules define the maximum acceptable drop. The gate fails when the candidate crosses that threshold.

## Evidence boundary

A deterministic fixture proves framework mechanics, not production AI quality. Production claims require a real system, a documented evaluation population, reproducible configuration, and observed results.
