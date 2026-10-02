from ai_eval_engineering.regression import BaselineRecord, RegressionRule, evaluate_gate


def test_gate_passes_within_allowed_drop() -> None:
    baseline = BaselineRecord("suite-1", "model-a", {"accuracy": 0.9})
    result = evaluate_gate(baseline, {"accuracy": 0.89}, [RegressionRule("accuracy", 0.02)])
    assert result.passed


def test_gate_fails_on_regression() -> None:
    baseline = BaselineRecord("suite-1", "model-a", {"accuracy": 0.9})
    result = evaluate_gate(baseline, {"accuracy": 0.85}, [RegressionRule("accuracy", 0.02)])
    assert not result.passed
    assert result.failures[0].metric == "accuracy"
