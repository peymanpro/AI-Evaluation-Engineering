import json

from ai_eval_engineering.dataset import load_suite, promote_regression_case
from ai_eval_engineering.domain import EvaluationCase, EvaluationSuite


def test_dataset_loader_preserves_version_and_ids(tmp_path) -> None:
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({
        "version": "v1",
        "cases": [{"id": "a", "input": {"x": 1}, "expected": 1, "tags": ["golden"]}]
    }), encoding="utf-8")
    suite = load_suite(path)
    assert isinstance(suite, EvaluationSuite)
    assert suite.version == "v1"
    assert suite.cases[0].tags == ("golden",)


def test_failed_case_can_be_promoted_to_regression_suite(tmp_path) -> None:
    base = EvaluationSuite(version="v1", cases=(
        EvaluationCase("base", {"x": 1}, expected=1),
    ))
    failed = EvaluationCase("known-failure", {"x": 2}, expected=2, tags=("factual",))
    path = tmp_path / "regression.json"
    result = promote_regression_case(base, failed, path)
    assert result.version == "v1+regression"
    assert result.cases[-1].risk_category == "regression"
    assert "regression" in result.cases[-1].tags
    assert load_suite(path).cases[-1].id == "known-failure"
