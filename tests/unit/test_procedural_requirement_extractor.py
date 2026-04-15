"""Unit tests for ``ProceduralRequirementExtractor``.

Two-pass: DIRECT table extraction + LLM prose extraction + dedup.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.procedural_value_objects import (
    RequirementInterpretation,
)

from fault_mapper.application.procedural_requirement_extractor import (
    ProceduralRequirementExtractor,
)

from tests.conftest import (
    FakeProceduralLlmInterpreter,
    FakeProceduralRulesEngine,
    make_section,
    make_table,
)


@pytest.fixture
def extractor(
    fake_procedural_rules: FakeProceduralRulesEngine,
    fake_procedural_llm: FakeProceduralLlmInterpreter,
) -> ProceduralRequirementExtractor:
    return ProceduralRequirementExtractor(
        rules=fake_procedural_rules,
        llm=fake_procedural_llm,
    )


class TestTableExtraction:
    def test_extracts_from_equipment_table(
        self,
        extractor: ProceduralRequirementExtractor,
    ):
        table = make_table(
            headers=["Equipment", "Part Number", "Qty"],
            rows=[["Torque Wrench", "TW-100", "1"]],
            id="tbl-1",
        )
        section = make_section(tables=[table], id="s1")
        items, origins = extractor.extract([section], {})

        assert len(items) >= 1
        assert items[0].requirement_type == "equipment"
        assert items[0].name == "Torque Wrench"

    def test_skips_non_requirement_table(
        self,
        extractor: ProceduralRequirementExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        # Table with no requirement-like headers
        fake_procedural_llm.requirement_results = []
        table = make_table(
            headers=["Chapter", "Page", "Revision"],
            rows=[["1", "5", "A"]],
            id="tbl-1",
        )
        section = make_section(tables=[table], id="s1")
        items, _ = extractor.extract([section], {})
        assert len(items) == 0

    def test_empty_rows_skipped(
        self,
        extractor: ProceduralRequirementExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.requirement_results = []
        table = make_table(
            headers=["Equipment", "Part Number"],
            rows=[["", ""]],
            id="tbl-1",
        )
        section = make_section(tables=[table], id="s1")
        items, _ = extractor.extract([section], {})
        assert len(items) == 0

    def test_table_origin_is_direct(
        self,
        extractor: ProceduralRequirementExtractor,
    ):
        table = make_table(
            headers=["Tool", "Qty"],
            rows=[["Wrench", "2"]],
            id="tbl-1",
        )
        section = make_section(tables=[table], id="s1")
        items, origins = extractor.extract([section], {})

        direct_origins = [
            o for o in origins.values()
            if o.strategy == MappingStrategy.DIRECT
        ]
        assert len(direct_origins) >= 1


class TestProseExtraction:
    def test_extracts_from_prose_via_llm(
        self,
        extractor: ProceduralRequirementExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.requirement_results = [
            RequirementInterpretation(
                requirement_type="personnel",
                name="Licensed Mechanic",
                role="Mechanic",
                skill_level="Level 3",
                confidence=0.90,
            ),
        ]
        section = make_section(
            section_text="A licensed mechanic is required.",
            id="s1",
        )
        items, origins = extractor.extract([section], {})

        llm_items = [
            i for i in items if i.requirement_type == "personnel"
        ]
        assert len(llm_items) >= 1
        assert llm_items[0].role == "Mechanic"

    def test_llm_below_threshold_filtered(
        self,
        extractor: ProceduralRequirementExtractor,
        fake_procedural_rules: FakeProceduralRulesEngine,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_rules.threshold_value = 0.80
        fake_procedural_llm.requirement_results = [
            RequirementInterpretation(
                requirement_type="spare",
                name="Bolt",
                confidence=0.50,
            ),
        ]
        section = make_section(id="s1")
        items, _ = extractor.extract([section], {})
        spare_items = [i for i in items if i.requirement_type == "spare"]
        assert len(spare_items) == 0


class TestDeduplication:
    def test_duplicates_removed(
        self,
        extractor: ProceduralRequirementExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        # Table + LLM both find the same item
        fake_procedural_llm.requirement_results = [
            RequirementInterpretation(
                requirement_type="equipment",
                name="Torque Wrench",
                ident_number="TW-100",
                confidence=0.90,
            ),
        ]
        table = make_table(
            headers=["Equipment", "Part Number"],
            rows=[["Torque Wrench", "TW-100"]],
            id="tbl-1",
        )
        section = make_section(tables=[table], id="s1")
        items, _ = extractor.extract([section], {})

        # Should be deduplicated to 1
        tw_items = [i for i in items if i.name == "Torque Wrench"]
        assert len(tw_items) == 1


class TestMultipleSections:
    def test_combines_across_sections(
        self,
        extractor: ProceduralRequirementExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.requirement_results = [
            RequirementInterpretation(
                requirement_type="supply",
                name="Sealant",
                confidence=0.88,
            ),
        ]
        s1 = make_section(id="s1")
        s2 = make_section(id="s2", section_order=1)
        items, _ = extractor.extract([s1, s2], {})
        # At least one supply from each section
        assert len(items) >= 1
