from __future__ import annotations

from pathlib import Path

from ai_eval_engineering import (
    EvaluationRun,
    ReleaseMetricPolicy,
    compare_failure_runs,
    evaluate_release_candidate,
    load_promptfoo_json,
)


FIXTURES = Path(__file__).parent / "fixtures"
PROVIDER_ID = "openai:mock:answerer"
PROMPT_IDX = 0
SUITE_VERSION = "arithmetic-suite-v1"
SYSTEM_NAME = "arithmetic-assistant"


def load_pair() -> tuple[EvaluationRun, EvaluationRun]:
    baseline = load_promptfoo_json(
        FIXTURES / "promptfoo-baseline-v3.json",
        system_name=SYSTEM_NAME,
        system_version="model-v1",
        suite_version=SUITE_VERSION,
        provider_id=PROVIDER_ID,
        prompt_idx=PROMPT_IDX,
    )
    candidate = load_promptfoo_json(
        FIXTURES / "promptfoo-candidate-v3.json",
        system_name=SYSTEM_NAME,
        system_version="model-v2",
        suite_version=SUITE_VERSION,
        provider_id=PROVIDER_ID,
        prompt_idx=PROMPT_IDX,
    )
    return baseline, candidate


def test_promptfoo_baseline_candidate_flow_reaches_release_gate_and_failure_delta() -> None:
    baseline, candidate = load_pair()

    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [
            ReleaseMetricPolicy(
                "promptfoo",
                direction="higher_is_better",
                max_allowed_regression=0.02,
                min_cases=30,
            )
        ],
        confidence=0.95,
        resamples=2000,
        seed=7,
    )
    delta = compare_failure_runs(
        baseline,
        candidate,
    )

    assert decision.status == "FAIL"
    assert decision.baseline_system_version == "model-v1"
    assert decision.candidate_system_version == "model-v2"
    assert decision.metrics[0].sample_size == 30
    assert decision.metrics[0].baseline_mean == 0.8
    assert decision.metrics[0].candidate_mean == 0.5
    assert decision.metrics[0].confidence_interval is not None
    assert decision.metrics[0].confidence_interval.upper < -0.02

    assert delta.new_failure_count == 11
    assert delta.resolved_failure_count == 2
    assert delta.persistent_failure_count == 4
    assert delta.has_new_regressions
    assert not delta.all_baseline_failures_resolved
    assert {item.case.id for item in delta.new_failures} == {
        f"test-{index:06d}" for index in range(6, 17)
    }
    assert {item.case.id for item in delta.resolved_failures} == {
        "test-000004",
        "test-000005",
    }
    assert {item.baseline.case.id for item in delta.persistent_failures} == {
        "test-000000",
        "test-000001",
        "test-000002",
        "test-000003",
    }
