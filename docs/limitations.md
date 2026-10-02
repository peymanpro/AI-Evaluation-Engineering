# Limitations and Non-Goals

- Deterministic fixtures do not establish production model quality.
- The fake judge verifies the judge contract and calibration mechanics; it is not evidence about the quality of a particular external LLM judge.
- The adversarial suite is intentionally small and is not a comprehensive security benchmark.
- Offline evaluation does not imply online product impact.
- Contract-snapshot integrations verify adapter compatibility and evaluation semantics; they do not execute the sibling applications inside this CI job.
- Quality/cost/latency frontiers expose trade-offs without automatically selecting a preferred system.
- Online experimentation, cloud-provider integrations, and production analytics adapters remain outside the V1.1 boundary.
