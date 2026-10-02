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


def test_building_software_integration_contract() -> None:
    result, spec = run_contract_demo(
        building_software_suite(),
        building_software_adapter(),
        standard_integration_graders("peymanpro/Building-Software-With-LLMs"),
    )
    assert spec.repository == "peymanpro/Building-Software-With-LLMs"
    assert result["passed_cases"] == 4


def test_evidence_rag_integration_contract() -> None:
    result, spec = run_contract_demo(
        evidence_rag_suite(),
        evidence_rag_adapter(),
        standard_integration_graders("peymanpro/Evidence-Grounded-RAG"),
    )
    assert spec.repository == "peymanpro/Evidence-Grounded-RAG"
    assert result["passed_cases"] == 2


def test_how_agents_integration_contract() -> None:
    result, spec = run_contract_demo(
        how_agents_suite(),
        how_agents_adapter(),
        standard_integration_graders("peymanpro/HowAgentsWork"),
    )
    assert spec.repository == "peymanpro/HowAgentsWork"
    assert result["passed_cases"] == 3
