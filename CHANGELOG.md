# Changelog

Notable user-facing changes are recorded here. This project follows semantic versioning where practical; pre-1.0 releases may still refine public APIs.

## Unreleased

### Added
- Bounded-concurrency asynchronous evaluation runner with stable suite-order results, shared synchronous graders, and fail-fast cancellation semantics.
- Optional per-case async adapter deadlines with cancellation and explicit failure instead of an indefinitely blocked run.
- Preflight suite/manifest validation and per-case output/grader contract checks to prevent inconsistent or non-finite evidence from entering a run.
- Native-async OpenAI-compatible judge and grader that can run inside bounded concurrent evaluations without blocking on a synchronous model SDK call.
- Native-async OpenAI-compatible structured-output judge and async grader integration for bounded asynchronous evaluation runs.

## 0.2.0 - 2026-10-26

### Added
- Optional `openai` extra and an OpenAI-compatible LLM judge using Chat Completions JSON Schema Structured Outputs.
- `OpenAIJudgeGrader` to connect a configured judge to the existing `EvaluationRunner` grader contract, with an explicit label-to-pass mapping.
- Provider/model/request and token-usage metadata for LLM judge results, without retaining the raw provider response.
- Promptfoo v3 JSON import, versioned external-run JSON interchange with a packaged schema resource, decision-grade paired release gates, and case-level failure-delta reporting.
- Persistent failure memory, class-aware judge calibration metrics, and a deterministic baseline/candidate workflow that joins Promptfoo import, release decisions, and regression triage.
- PyPI publishing automation via Trusted Publishing, scoped to a separate publication job and backed by distribution metadata checks.

### Quality and release engineering
- The CI suite contains 197 automated tests at the release-preparation commit, plus Ruff, mypy, and deterministic demonstration checks.
- Synthetic fixtures are explicitly identified as test data, not real provider benchmark results.
- The base installation remains free of mandatory runtime dependencies; the live judge SDK is optional.

### Limitations
- The LLM judge has deterministic fake-client tests but is not tested against a live provider in CI; actual judge quality still requires human-labelled calibration.
- The Promptfoo adapter supports its v3 JSON export envelope only.
- Online experimentation primitives and sibling-project integrations are not a deployed live experimentation platform or live-process integrations.
- PyPI upload requires a Trusted Publisher configured for this repository/workflow in the package owner's PyPI account.
