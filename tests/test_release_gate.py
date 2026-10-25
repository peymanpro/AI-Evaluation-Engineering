from __future__ import annotations

import pytest

from ai_eval_engineering.domain import (
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    GraderResult,
    RunMetadata,
    SystemOutput,
)
from ai_eval_engineering.release_gate import (
    ReleaseMetricPolicy,
    evaluate_release_candidate,
)


def make_run(
    version: str,
    scores: list[float],
    *,
    suite_version: str = "suite-v1",
    case_ids: list[str] | None = None,
    prompt_prefix: str = "question",
    metric: str = "quality",
    extra_metrics: dict[str, list[float]] | None = None,
) -> EvaluationRun:
    ids = case_ids or [f"case-{index}" for index in range(len(scores))]
    assert len(ids) == len(scores)
    for extra_name, extra_scores in (extra_metrics or {}).items():
        assert extra_name != metric
        assert len(extra_scores) == len(scores)
    cases = []
    for index, (case_id, score) in enumerate(zip(ids, scores, strict=True)):
        case = EvaluationCase(
            id=case_id,
            input={"prompt": f"{prompt_prefix} {index}"},
            expected={"answer": f"expected {index}"},
            metadata={"source": "test-fixture"},
            tags=("release-test",),
        )
        output = SystemOutput(case_id=case_id, output={"answer": f"actual {index}"})
        graders = [
            GraderResult(
                grader=metric,
                passed=True,
                score=score,
                details="deterministic test score",
            )
        ]
        for extra_name, extra_scores in (extra_metrics or {}).items():
            graders.append(
                GraderResult(
                    grader=extra_name,
                    passed=True,
                    score=extra_scores[index],
                    details="deterministic test score",
                )
            )
        cases.append(CaseResult(case=case, output=output, graders=tuple(graders)))
    return EvaluationRun(
        manifest=RunMetadata(
            run_id=f"run-{version}",
            suite_version=suite_version,
            system_name="example-assistant",
            system_version=version,
            configuration={},
            seed=7,
            timestamp_utc="2026-10-25T00:00:00Z",
        ),
        cases=tuple(cases),
    )


def test_release_gate_passes_when_paired_change_is_within_tolerance() -> None:
    baseline = make_run("v1", [0.5, 0.6, 0.7, 0.8])
    candidate = make_run("v2", [0.6, 0.7, 0.8, 0.9])

    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [ReleaseMetricPolicy("quality", min_cases=2)],
        resamples=500,
        seed=11,
    )

    assert decision.status == "PASS"
    assert decision.passed
    assert decision.metrics[0].observed_difference == pytest.approx(0.1)
    assert decision.metrics[0].confidence_interval is not None
    assert decision.metrics[0].confidence_interval.lower <= 0.1


def test_release_gate_fails_when_paired_regression_exceeds_tolerance() -> None:
    baseline = make_run("v1", [0.8, 0.8, 0.8, 0.8])
    candidate = make_run("v2", [0.6, 0.6, 0.6, 0.6])

    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [
            ReleaseMetricPolicy(
                "quality",
                direction="higher_is_better",
                max_allowed_regression=0.1,
                min_cases=2,
            )
        ],
        resamples=500,
        seed=11,
    )

    assert decision.status == "FAIL"
    assert not decision.passed
    assert decision.metrics[0].status == "FAIL"


def test_overlapping_interval_is_inconclusive_not_pass_or_fail() -> None:
    baseline = make_run("v1", [0.0, 1.0, 0.0, 1.0])
    candidate = make_run("v2", [1.0, 0.0, 0.0, 1.0])

    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [ReleaseMetricPolicy("quality", min_cases=2)],
        resamples=1000,
        seed=17,
    )

    assert decision.status == "INCONCLUSIVE"
    assert decision.metrics[0].status == "INCONCLUSIVE"
    assert decision.metrics[0].confidence_interval is not None


def test_lower_is_better_metric_passes_when_latency_improves() -> None:
    baseline = make_run("v1", [200.0, 210.0, 190.0], metric="latency_ms")
    candidate = make_run("v2", [150.0, 160.0, 140.0], metric="latency_ms")

    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [
            ReleaseMetricPolicy(
                "latency_ms",
                direction="lower_is_better",
                max_allowed_regression=0.0,
                min_cases=2,
            )
        ],
        resamples=500,
    )

    assert decision.status == "PASS"
    assert decision.metrics[0].observed_difference == -50.0
    assert decision.metrics[0].favorable_difference == 50.0


def test_lower_is_better_metric_fails_when_latency_regresses() -> None:
    baseline = make_run("v1", [100.0, 100.0, 100.0], metric="latency_ms")
    candidate = make_run("v2", [150.0, 150.0, 150.0], metric="latency_ms")

    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [
            ReleaseMetricPolicy(
                "latency_ms",
                direction="lower_is_better",
                max_allowed_regression=10.0,
                min_cases=2,
            )
        ],
        resamples=500,
    )

    assert decision.status == "FAIL"


def test_inadequate_sample_is_inconclusive_without_confidence_interval() -> None:
    baseline = make_run("v1", [0.6, 0.7])
    candidate = make_run("v2", [0.8, 0.9])

    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [ReleaseMetricPolicy("quality", min_cases=3)],
        resamples=500,
    )

    assert decision.status == "INCONCLUSIVE"
    assert decision.metrics[0].confidence_interval is None
    assert "at least 3" in decision.metrics[0].reason


def test_different_suite_versions_are_invalid_evidence() -> None:
    baseline = make_run("v1", [0.7, 0.8], suite_version="suite-v1")
    candidate = make_run("v2", [0.8, 0.9], suite_version="suite-v2")

    decision = evaluate_release_candidate(
        baseline, candidate, [ReleaseMetricPolicy("quality", min_cases=2)]
    )

    assert decision.status == "INVALID_EVIDENCE"
    assert "different suite versions" in decision.summary()


def test_changed_case_definition_is_invalid_evidence() -> None:
    baseline = make_run("v1", [0.7, 0.8], prompt_prefix="baseline question")
    candidate = make_run("v2", [0.8, 0.9], prompt_prefix="changed question")

    decision = evaluate_release_candidate(
        baseline, candidate, [ReleaseMetricPolicy("quality", min_cases=2)]
    )

    assert decision.status == "INVALID_EVIDENCE"
    assert "case definition changed" in decision.summary()


def test_unmatched_case_ids_are_invalid_evidence() -> None:
    baseline = make_run("v1", [0.7, 0.8, 0.9], case_ids=["a", "b", "c"])
    candidate = make_run("v2", [0.8, 0.9, 1.0], case_ids=["a", "b", "x"])

    decision = evaluate_release_candidate(
        baseline, candidate, [ReleaseMetricPolicy("quality", min_cases=2)]
    )

    assert decision.status == "INVALID_EVIDENCE"
    assert any("missing case ids" in reason for reason in decision.reasons)
    assert any("unmatched case ids" in reason for reason in decision.reasons)


def test_missing_metric_in_any_case_is_invalid_evidence() -> None:
    baseline = make_run("v1", [0.7, 0.8, 0.9])
    candidate = make_run("v2", [0.8, 0.9, 1.0])
    candidate_cases = list(candidate.cases)
    candidate_cases[1] = CaseResult(
        case=candidate_cases[1].case,
        output=candidate_cases[1].output,
        graders=(),
    )
    candidate = EvaluationRun(candidate.manifest, tuple(candidate_cases))

    decision = evaluate_release_candidate(
        baseline, candidate, [ReleaseMetricPolicy("quality", min_cases=2)]
    )

    assert decision.status == "INVALID_EVIDENCE"
    assert "missing grader metric" in decision.summary()


def test_output_case_id_mismatch_is_invalid_evidence() -> None:
    baseline = make_run("v1", [0.7, 0.8])
    candidate = make_run("v2", [0.8, 0.9])
    bad = candidate.cases[0]
    candidate = EvaluationRun(
        candidate.manifest,
        (
            CaseResult(
                bad.case,
                SystemOutput(case_id="wrong-id", output=bad.output.output),
                bad.graders,
            ),
            *candidate.cases[1:],
        ),
    )

    decision = evaluate_release_candidate(
        baseline, candidate, [ReleaseMetricPolicy("quality", min_cases=2)]
    )

    assert decision.status == "INVALID_EVIDENCE"
    assert any("does not match case id" in reason for reason in decision.reasons)


def test_duplicate_metric_policies_are_rejected() -> None:
    run = make_run("v1", [0.7, 0.8])
    with pytest.raises(ValueError, match="duplicate metric"):
        evaluate_release_candidate(
            run,
            run,
            [
                ReleaseMetricPolicy("quality", min_cases=2),
                ReleaseMetricPolicy("quality", min_cases=2),
            ],
        )



def test_non_finite_grader_score_is_invalid_evidence() -> None:
    baseline = make_run("v1", [0.7, 0.8])
    candidate = make_run("v2", [0.8, 0.9])
    bad = candidate.cases[0]
    candidate = EvaluationRun(
        candidate.manifest,
        (
            CaseResult(
                bad.case,
                bad.output,
                (
                    GraderResult(
                        grader="quality",
                        passed=False,
                        score=float("nan"),
                        details="invalid test score",
                    ),
                ),
            ),
            *candidate.cases[1:],
        ),
    )

    decision = evaluate_release_candidate(
        baseline, candidate, [ReleaseMetricPolicy("quality", min_cases=2)]
    )

    assert decision.status == "INVALID_EVIDENCE"
    assert any("non-finite score" in reason for reason in decision.reasons)


def test_policy_rejects_negative_tolerance_and_too_small_minimum() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ReleaseMetricPolicy("quality", max_allowed_regression=-0.1)
    with pytest.raises(ValueError, match="at least 2"):
        ReleaseMetricPolicy("quality", min_cases=1)



def test_multi_metric_gate_uses_bonferroni_adjusted_confidence() -> None:
    baseline = make_run(
        "v1",
        [0.5, 0.6, 0.7, 0.8],
        extra_metrics={"latency_ms": [200.0, 210.0, 190.0, 205.0]},
    )
    candidate = make_run(
        "v2",
        [0.6, 0.7, 0.8, 0.9],
        extra_metrics={"latency_ms": [150.0, 160.0, 140.0, 155.0]},
    )

    decision = evaluate_release_candidate(
        baseline,
        candidate,
        [
            ReleaseMetricPolicy("quality", min_cases=2),
            ReleaseMetricPolicy(
                "latency_ms", direction="lower_is_better", min_cases=2
            ),
        ],
        confidence=0.95,
        resamples=500,
        seed=11,
    )

    assert decision.status == "PASS"
    assert decision.confidence_level == 0.95
    assert all(item.confidence_interval is not None for item in decision.metrics)
    assert all(
        item.confidence_interval.confidence == pytest.approx(0.975)
        for item in decision.metrics
        if item.confidence_interval is not None
    )
