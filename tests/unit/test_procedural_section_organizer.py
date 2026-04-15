"""Unit tests for ``ProceduralSectionOrganizer``.

Two-pass classification: RULE → LLM fallback → default GENERAL.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.procedural_enums import ProceduralSectionType
from fault_mapper.domain.procedural_value_objects import (
    SectionClassificationResult,
)

from fault_mapper.application.procedural_section_organizer import (
    ProceduralSectionOrganizer,
)

from tests.conftest import (
    FakeProceduralLlmInterpreter,
    FakeProceduralRulesEngine,
    make_section,
)


@pytest.fixture
def organizer(
    fake_procedural_rules: FakeProceduralRulesEngine,
    fake_procedural_llm: FakeProceduralLlmInterpreter,
) -> ProceduralSectionOrganizer:
    return ProceduralSectionOrganizer(
        rules=fake_procedural_rules,
        llm=fake_procedural_llm,
    )


class TestRuleClassification:
    """Tests where rules return a definite section type."""

    def test_rule_classification_used(
        self,
        organizer: ProceduralSectionOrganizer,
        fake_procedural_rules: FakeProceduralRulesEngine,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_rules.classify_section_value = (
            ProceduralSectionType.REMOVAL
        )
        sections = [make_section(section_title="Remove Component", id="s1")]
        shells, origins = organizer.organize(sections)

        assert len(shells) == 1
        assert shells[0].section_type == ProceduralSectionType.REMOVAL
        assert origins["section_type.s1"].strategy == MappingStrategy.RULE
        # LLM should NOT have been called
        assert len(fake_procedural_llm.calls["classify_section"]) == 0

    def test_shell_has_correct_metadata(
        self,
        organizer: ProceduralSectionOrganizer,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        fake_procedural_rules.classify_section_value = (
            ProceduralSectionType.INSPECTION
        )
        sections = [make_section(
            section_title="Inspect Valve",
            section_order=3,
            level=2,
            id="s1",
        )]
        shells, _ = organizer.organize(sections)

        assert shells[0].title == "Inspect Valve"
        assert shells[0].section_order == 3
        assert shells[0].level == 2
        assert shells[0].source_section_id == "s1"


class TestLlmFallback:
    """Tests where rules return None → LLM fallback."""

    def test_llm_above_threshold_classifies(
        self,
        organizer: ProceduralSectionOrganizer,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.classification_result = SectionClassificationResult(
            section_type=ProceduralSectionType.SERVICING,
            confidence=0.92,
            reasoning="service procedure",
        )
        sections = [make_section(id="s1")]
        shells, origins = organizer.organize(sections)

        assert shells[0].section_type == ProceduralSectionType.SERVICING
        assert origins["section_type.s1"].strategy == MappingStrategy.LLM
        assert origins["section_type.s1"].confidence == 0.92

    def test_llm_below_threshold_defaults_to_general(
        self,
        organizer: ProceduralSectionOrganizer,
        fake_procedural_rules: FakeProceduralRulesEngine,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_rules.threshold_value = 0.80
        fake_procedural_llm.classification_result = SectionClassificationResult(
            section_type=ProceduralSectionType.TEST,
            confidence=0.40,
            reasoning="unsure",
        )
        sections = [make_section(id="s1")]
        shells, origins = organizer.organize(sections)

        assert shells[0].section_type == ProceduralSectionType.GENERAL
        assert origins["section_type.s1"].confidence == 0.5


class TestOrdering:
    def test_sections_sorted_by_section_order(
        self,
        organizer: ProceduralSectionOrganizer,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        fake_procedural_rules.classify_section_value = (
            ProceduralSectionType.PROCEDURE
        )
        sections = [
            make_section(section_order=3, id="s3"),
            make_section(section_order=1, id="s1"),
            make_section(section_order=2, id="s2"),
        ]
        shells, _ = organizer.organize(sections)
        orders = [s.section_order for s in shells]
        assert orders == [1, 2, 3]

    def test_empty_input_returns_empty(
        self,
        organizer: ProceduralSectionOrganizer,
    ):
        shells, origins = organizer.organize([])
        assert shells == []
        assert origins == {}

    def test_section_id_falls_back_to_order(
        self,
        organizer: ProceduralSectionOrganizer,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        fake_procedural_rules.classify_section_value = (
            ProceduralSectionType.GENERAL
        )
        sections = [make_section(section_order=5, id=None)]
        shells, origins = organizer.organize(sections)
        assert shells[0].section_id == "sec_5"
        assert "section_type.section_5" in origins
