# Limitations and Non-Goals

- Deterministic fixtures do not establish production model quality.
- The fake judge verifies judge-contract and calibration mechanics; it is not evidence about the quality of a particular external LLM judge.
- The adversarial suite is intentionally small and is not a comprehensive security benchmark.
- Offline evaluation does not imply online product impact.
- Contract-snapshot integrations verify adapter compatibility and evaluation semantics; they do not execute the sibling applications inside this CI job.
- Quality/cost/latency frontiers expose trade-offs without automatically selecting a preferred system.
- Online experimentation, cloud-provider integrations, and production analytics adapters remain outside the V1.1 boundary.

- An online evidence assessment marked `sufficient` means only that the configured data-integrity and minimum-count checks passed. It is not a power analysis, proof of causal validity, or evidence that an effect is practically meaningful.
- Duplicate exposure/outcome records and outcomes without a matching exposure invalidate the configured online-evidence checks; they must not silently increase sample counts.
- A bootstrap confidence interval is not reported for an online comparison when either group contains fewer than two observations. The descriptive difference remains available, and the missing interval must not be interpreted as certainty.
- The independent-sample bootstrap difference interval assumes separate groups. Results paired by case or prompt require a paired method rather than independent resampling.

- The decision-grade release gate requires baseline and candidate runs to share the same system name, suite version, case identifiers, and case definitions. This catches common comparison-integrity problems but cannot prove the grader implementations or their semantic correctness are unchanged.
- Release-gate confidence intervals use a percentile bootstrap over per-case paired differences. This is appropriate only when case-level scores are genuinely matched and representative of the target evaluation population; it is not a formal power analysis or production-wide guarantee.
- A release `PASS` means the configured intervals meet the configured tolerances on the supplied suite. Metric direction, practical tolerance, suite quality, and the risk of evaluating many metrics remain user responsibilities.
- `INCONCLUSIVE` is intentional when the configured minimum case count is not met or when the uncertainty interval overlaps a release threshold; it must not be interpreted as a pass.
- When multiple metrics are gated in one release decision, the engine applies a Bonferroni adjustment to the requested confidence level. This is conservative, but bootstrap interval coverage is approximate and should not be described as a formal statistical guarantee.
- Failure regression memory is a local JSONL artifact, not a secure vault. It omits observed model outputs by default, but case inputs, expected values, metadata, and grader details may contain sensitive data and must be reviewed or redacted before storage.
- Failure-memory identity is tied to suite version, system name, case definition, and grader name. It does not version grader implementation or rubric semantics; bump the suite or other external versioning metadata when those semantics change.
- Merged failure records should be processed in chronological run order so first/last-seen history remains meaningful.
- Judge calibration metrics compare a judge with the supplied human labels; they do not verify that human labels are correct, that the sample represents deployment traffic, or that the judge is fair on unobserved populations. Report per-class metrics and sample counts, especially when label distributions are imbalanced.
- Macro precision treats undefined per-label precision as zero for labels present in the human reference set. Cohen's kappa is omitted when its expected-agreement denominator is zero.
- Failure-delta comparison is intentionally strict: both runs must use the same system name, suite version, exact case definitions, and per-case grader names. It does not infer causal root causes; it classifies observed failure state changes only.
- A persistent failure score delta is candidate score minus baseline score in the grader's raw scale. It is not automatically interpreted as improvement because grader direction and meaning are application-defined.
- The external-run importer defines a versioned, provider-neutral interchange envelope; it is not a native SDK integration for any external evaluation vendor. A source-specific adapter is still needed to map vendor output into the envelope.
- Imported evaluation runs preserve case inputs, expected values, observed outputs, traces, and grader details. Those fields may contain sensitive information; review/redact payloads and protect files according to the data policy of the system being evaluated.
- Schema validation can verify structure, type constraints, IDs, finite numeric values, and declared grader presence. It cannot prove that an external tool computed its metrics correctly or that its timestamp, run identity, rubric, and system-version claims are truthful.
- The Promptfoo adapter currently accepts the documented v3 JSON export envelope with result rows at `results.results`. It does not support Promptfoo JSONL, CSV, JUnit XML, v2 export files, or red-team-specific result formats.
- Promptfoo exports can contain prompt text, test variables, expected assertions, raw model outputs, traces, and configuration that may expose sensitive data. Review/redact source exports and protect normalized run artifacts before storing or sharing them.
- When an export contains multiple providers or prompt indices, an adapter call must select a single provider/prompt slice. The caller supplies system name/version and suite version; the adapter cannot infer the intended release identity or prove that the suite version truly identifies unchanged test semantics.
- Import validation checks the documented structure and numeric constraints but cannot prove that Promptfoo's assertions, scores, latency, cost, or provider metadata were computed correctly.
