# Capability audit and implementation roadmap

This is a development roadmap, not a release plan. The package remains in feature development after the
GitHub Release `v0.2.0`; PyPI publication is intentionally deferred until the selected capabilities
are implemented and validated.

## What already exists

The current repository is more than a basic evaluation loop. It includes:

- typed cases, versioned suites, strict JSON interchange, preflight contract validation, and run manifests;
- synchronous and bounded-concurrency asynchronous runners, per-case async deadlines, and resumable checkpoints;
- deterministic exact-match, schema, rule-based, and trajectory graders, plus optional synchronous and native-async OpenAI-compatible judges;
- judge calibration against supplied human labels, confidence intervals, paired comparisons, direction-aware regression gates, and decision-grade release evaluation;
- Promptfoo v3 import, failure-delta reports, persistent failure memory, auditable evidence packages, a recorded-run CLI, post-run budget assessment, online-evidence guardrails, and cost/latency trade-off frontiers.

These are substantive foundations. The main risk is not the absence of a long feature list; it is whether each primitive is sufficiently diagnostic, reproducible, safe to use, and integrated into ordinary evaluation workflows.

## Priority order

### P1 — Subgroup/slice diagnostics (implemented)

**Problem:** An overall pass rate or mean score can look healthy while failures concentrate in a security category, locale, customer tier, language, or other subset.

**Capability:** `analyze_run_slices` groups recorded results by case tags, risk category, or one explicitly selected scalar field in case metadata. It reports overall case pass rate and score, per-grader results, sample counts, and a visible low-sample flag. The `ai-eval slices` command exposes the same functionality for stored runs.

**Acceptance criteria:** deterministic grouping; no silent dropping of unclassified cases; explicit overlap semantics for tags; per-grader breakdowns; small groups remain visible; tests for malformed metadata; no unsupported claims of statistical significance.

### P1 — Explicit transient-failure retry policy

**Problem:** A transient API/network failure currently fails the run. Checkpoints make manual resume safe, but large runs still need manual intervention and retry rules are easy to implement inconsistently.

**Proposed capability:** a shared, opt-in retry policy for system-adapter calls, with bounded attempts, exponential backoff, and a caller-supplied retry predicate. Do not retry graders or schema/contract validation errors. Keep zero retries as the default, preserve checkpoint semantics, and document that a timeout or transport exception can occur after a provider processed and billed a request.

**Guardrail:** never retry all exceptions by default, and never imply that retrying a request is cost-free or idempotent.

### P1 — Common deterministic grader primitives (partially implemented)

**Problem:** `RuleBasedGrader` is extensible, but simple common checks should not require each consumer to write and test custom code.

**Implemented:** `ContainsGrader`, `RegexGrader`, and `NumericToleranceGrader` provide dependency-free, deterministic checks with explicit type-mismatch behavior and documented score semantics. Regex patterns can be configured once or supplied in each case's expected value; numeric tolerance combines absolute and relative error bounds.

**Remaining:** structured-field assertions and score composition should be designed separately so their expected-value contracts remain unambiguous when one run uses multiple graders. Avoid adding a broad "metric zoo" that duplicates application-specific rules.

**Guardrail:** built-in graders must define normalization, type errors, pass/score behavior, and any untrusted-input limitations.

### P2 — Live budget guard

**Problem:** the existing budget policy evaluates recorded cost, token counts, and latency after the run. It cannot stop work before a provider charges for it.

**Proposed capability:** an opt-in run controller that checks known cumulative usage before scheduling additional cases and stops scheduling when a configured threshold is reached. Its contract must explicitly describe the possible overshoot from the request that crosses the limit and any already in-flight parallel requests. Never promise a hard spend cap without provider-side controls.

### P2 — Safe, version-aware caching

**Problem:** repeating a deterministic evaluation or resuming an equivalent experiment can repeat expensive calls.

**Proposed capability:** an optional cache keyed by the full case definition, system/version identity, adapter configuration, and relevant evaluator settings. Caching must be disabled by default for nondeterministic models; sensitive payload storage must be documented, and cache invalidation must be inspectable. Do not cache grader results across rubric/grader version changes.

### P2 — More first-class interoperability

**Problem:** the generic adapter protocol and Promptfoo import are intentionally provider-neutral, but consumers still write system-specific adapters and mappings.

**Proposed capability:** prefer small, tested adapters that translate existing result formats/contracts into the core model. Add a provider-specific SDK adapter only when its lifecycle, returned fields, dependencies, and version compatibility can be tested and documented without making the core depend on that SDK.

### Deliberately out of scope for now

- Publishing to PyPI before the feature set is selected, implemented, and verified.
- A hosted dashboard, central experiment database, or production analytics service.
- Claims that synthetic fixtures, fake judges, or contract-snapshot integrations establish real-world model quality.
- A large collection of subjective built-in LLM metrics without representative human-label calibration and explicit limitations.

## Design principles for every new capability

1. **Evidence first:** preserve case-level results and make missing evidence explicit.
2. **Safe defaults:** no provider calls, retries, caches, or publishing unless the caller configures them.
3. **Reproducibility:** define stable inputs, versions, ordering, and output contracts.
4. **Statistical honesty:** distinguish counts and descriptive summaries from inference, power, or causality.
5. **Operational usefulness:** include a real example, public API export, tests for failure paths, and documentation of privacy/cost implications.
6. **Small changes:** merge one coherent feature at a time; keep release/version work separate from feature development.

## Reference points

This roadmap uses established patterns from other evaluation frameworks as design references, not as a feature checklist:

- [DeepEval overview](https://deepeval.com/docs/introduction) separates datasets, metrics, traces, and end-to-end/trajectory/component evaluation, and describes caching and error configuration in its evaluation workflow.
- [DeepEval metrics overview](https://deepeval.com/docs/metrics-introduction) distinguishes reusable metrics from custom, application-specific evaluators.
- [LangSmith evaluation types](https://docs.langchain.com/langsmith/evaluation-types) distinguishes offline benchmarking/regression tests from online evaluation and lists LLM-as-judge, code, composite, summary, and pairwise evaluator approaches.

The intended differentiation here is a dependency-light, provider-neutral evaluation core with auditable run interchange and conservative statistical release decisions, rather than reproducing every hosted product or metric.
