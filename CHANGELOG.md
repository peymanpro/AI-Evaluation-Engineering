# Changelog

Notable user-facing changes are recorded here. This project follows semantic versioning where practical; pre-1.0 releases may still refine public APIs.

## Unreleased

### Added
- Versioned `release-policy-v1` JSON policies and a multi-metric `ai-eval compare --policy` mode with reproducible bootstrap settings, strict validation, and schema export; the legacy single-metric CLI remains supported.
- Bounded-concurrency asynchronous evaluation runner with stable suite-order results, shared synchronous graders, and fail-fast cancellation semantics.
- Optional per-case async adapter deadlines with cancellation and explicit failure instead of an indefinitely blocked run.
- Preflight suite/manifest validation and per-case output/grader contract checks to prevent inconsistent or non-finite evidence from entering a run.
- Native-async OpenAI-compatible judge and grader that can run inside bounded concurrent evaluations without blocking on a synchronous model SDK call.
- Post-run budget assessment for total/per-case measured cost, token usage, and per-case latency, with explicit exceeded, incomplete-evidence, and invalid-evidence outcomes.
- Opt-in live budgeted execution for synchronous and asynchronous runners, with fail-closed missing-usage handling and explicit partial-run results when further cases are not started.
- Reservation-based budget execution that reserves a per-case cost envelope before dispatch, accounts for all in-flight reservations and paid graders, rejects unbounded components before execution, and flags components that report charges above their declared allowance.
- Atomic checkpoints for synchronous and asynchronous runs, with strict suite/run-identity validation and resume of unfinished cases.
- A provider-free `ai-eval` CLI for external-run schema/validation, decision-grade baseline/candidate comparisons, and post-run budget gates with shell-friendly exit codes.
- Versioned evaluation-suite JSON interchange with atomic file I/O, strict validation, packaged schema, and `ai-eval validate-suite` / `ai-eval suite-schema` commands.
- Offline subgroup/slice analysis by tag, risk category, or an explicitly selected scalar case-metadata field, with per-grader summaries and a recorded-run CLI command.
- Dependency-free substring, regular-expression, and numeric-tolerance graders with explicit type handling, configurable targets, and deterministic pass/fail behavior.
- Opt-in transient adapter retries for sync and async runners, with bounded exponential backoff, explicit retryable exception types, retry event callbacks, and manifest-recorded policy configuration.
- JSON Pointer field assertions and a synchronous composite grader with explicit weights, weighted scores, and all/any/score-threshold pass policies.
- Public package exports and tests for the new grader primitives.

### Maintained
- PyPI upload remains opt-in and is not triggered by normal branch or tag pushes while capabilities are in development.

### Fixed
- The external-run-v1 importer and both schema copies reject unknown contract fields and cyclic in-memory Python containers, preventing silent evidence loss and ambiguous invalid payloads while preserving extensible application-owned JSON objects.

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
