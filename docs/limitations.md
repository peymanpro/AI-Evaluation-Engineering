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
