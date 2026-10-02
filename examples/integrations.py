"""Run the cross-repository contract demonstrations."""
from __future__ import annotations

import json

from ai_eval_engineering.integrations import (
    building_software_adapter,
    building_software_suite,
    evidence_rag_adapter,
    evidence_rag_suite,
    how_agents_adapter,
    how_agents_suite,
    run_contract_demo,
    standard_integration_graders,
)


def main() -> None:
    demonstrations = [
        (
            building_software_suite(),
            building_software_adapter(),
            "peymanpro/Building-Software-With-LLMs",
        ),
        (
            evidence_rag_suite(),
            evidence_rag_adapter(),
            "peymanpro/Evidence-Grounded-RAG",
        ),
        (
            how_agents_suite(),
            how_agents_adapter(),
            "peymanpro/HowAgentsWork",
        ),
    ]

    results = []
    for suite, adapter, repository in demonstrations:
        result, spec = run_contract_demo(
            suite,
            adapter,
            standard_integration_graders(repository),
        )
        results.append(
            {
                "repository": spec.repository,
                "revision": spec.revision,
                "suite": suite.version,
                "passed_cases": result["passed_cases"],
                "total_cases": len(suite.cases),
                "status": "passed" if result["passed_cases"] == len(suite.cases) else "failed",
            }
        )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
