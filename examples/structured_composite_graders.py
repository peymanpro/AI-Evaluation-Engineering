"""Demonstrate structured-field assertions and composite scoring offline."""

from __future__ import annotations

import json

from ai_eval_engineering import CompositeGrader, JsonFieldGrader
from ai_eval_engineering.domain import EvaluationCase, SystemOutput


def main() -> int:
    case = EvaluationCase("refund-decision", {}, expected=None)
    output = SystemOutput(
        "refund-decision",
        {
            "decision": "approved",
            "safety": {"allowed": True},
            "audit": {"reviewer": "human"},
        },
    )
    grader = CompositeGrader(
        [
            JsonFieldGrader(
                "/decision",
                name="decision",
                expected_value="approved",
            ),
            JsonFieldGrader(
                "/safety/allowed",
                name="safety",
                expected_value=True,
            ),
        ],
        weights=[0.75, 0.25],
        pass_mode="all",
    )
    result = grader.grade(case, output)
    print(
        json.dumps(
            {
                "grader": result.grader,
                "passed": result.passed,
                "score": result.score,
                "details": result.details,
                "metadata": result.metadata,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.passed and result.score == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
