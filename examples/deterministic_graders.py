"""Demonstrate deterministic graders without an external provider."""

from __future__ import annotations

import json

from ai_eval_engineering import ContainsGrader, NumericToleranceGrader, RegexGrader
from ai_eval_engineering.domain import EvaluationCase, SystemOutput


def main() -> int:
    checks = {
        "contains": ContainsGrader().grade(
            EvaluationCase("contains", {}, expected="delayed"),
            SystemOutput("contains", "Your shipment is DELAYED"),
        ),
        "order_id_format": RegexGrader(
            pattern=r"ORDER-[0-9]{4}",
            full_match=True,
        ).grade(
            EvaluationCase("order-id", {}, expected=None),
            SystemOutput("order-id", "ORDER-1234"),
        ),
        "numeric_tolerance": NumericToleranceGrader(
            abs_tol=0.05,
            rel_tol=0.01,
        ).grade(
            EvaluationCase("temperature", {}, expected=20.0),
            SystemOutput("temperature", 20.1),
        ),
    }
    payload = {
        name: {
            "passed": result.passed,
            "score": result.score,
            "details": result.details,
        }
        for name, result in checks.items()
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if all(result.passed for result in checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
