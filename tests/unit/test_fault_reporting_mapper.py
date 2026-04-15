"""Unit tests for ``FaultReportingMapper``.

Complex mapper using LLM + RULE via table classifier & schematic
correlator.  We inject fakes for all ports and collaborating services.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import (
    FaultEntryType,
    MappingStrategy,
    TableType,
)
from fault_mapper.domain.models import (
    FaultDescription,
    FaultEntry,
    FaultReportingContent,
)
from fault_mapper.domain.value_objects import (
    FaultDescriptionInterpretation,
    FieldOrigin,
    LruSruExtraction,
    TableClassification,
)

from fault_mapper.application.fault_reporting_mapper import FaultReportingMapper
from fault_mapper.application.fault_table_classifier import FaultTableClassifier
from fault_mapper.application.fault_schematic_correlator import (
    FaultSchematicCorrelator,
)

from tests.conftest import (
    FakeLlmInterpreter,
    FakeRulesEngine,
    make_chunk,
    make_schematic,
    make_schematic_component,
    make_section,
    make_table,
)


@pytest.fixture
def table_classifier(
    fake_rules: FakeRulesEngine,
    fake_llm: FakeLlmInterpreter,
) -> FaultTableClassifier:
    return FaultTableClassifier(rules=fake_rules, llm=fake_llm)


@pytest.fixture
def schematic_correlator(
    fake_llm: FakeLlmInterpreter,
    fake_rules: FakeRulesEngine,
) -> FaultSchematicCorrelator:
    return FaultSchematicCorrelator(llm=fake_llm, rules=fake_rules)


@pytest.fixture
def mapper(
    fake_llm: FakeLlmInterpreter,
    fake_rules: FakeRulesEngine,
    table_classifier: FaultTableClassifier,
    schematic_correlator: FaultSchematicCorrelator,
) -> FaultReportingMapper:
    return FaultReportingMapper(
        llm=fake_llm,
        rules=fake_rules,
        table_classifier=table_classifier,
        schematic_correlator=schematic_correlator,
    )


# ═══════════════════════════════════════════════════════════════════════
#  Basic mapping
# ═══════════════════════════════════════════════════════════════════════


class TestBasicMapping:
    def test_text_only_section_produces_entry(
        self,
        mapper: FaultReportingMapper,
    ):
        """Section with no tables → DIRECT fallback entry."""
        section = make_section(
            section_title="Engine Fault",
            section_text="Engine overheat detected.",
            tables=[],
            id="s1",
        )
        origins: dict[str, FieldOrigin] = {}
        content, origins = mapper.map([section], origins)

        assert isinstance(content, FaultReportingContent)
        assert len(content.fault_entries) == 1
        entry = content.fault_entries[0]
        assert entry.entry_type == FaultEntryType.DETECTED_FAULT
        assert entry.fault_descr is not None
        assert entry.fault_descr.descr == "Engine Fault"
        assert entry.detection_info is None
        assert entry.locate_and_repair is None

    def test_common_info_built_from_sections(
        self,
        mapper: FaultReportingMapper,
    ):
        section = make_section(
            section_title="Section Title",
            chunks=[make_chunk(chunk_text="Paragraph 1")],
        )
        content, _ = mapper.map([section], {})
        assert content.common_info is not None
        assert content.common_info.title == "Section Title"
        assert len(content.common_info.paragraphs) == 1

    def test_multiple_sections_produce_multiple_entries(
        self,
        mapper: FaultReportingMapper,
    ):
        s1 = make_section(id="s1", tables=[])
        s2 = make_section(id="s2", tables=[])
        content, _ = mapper.map([s1, s2], {})
        assert len(content.fault_entries) == 2

    def test_origins_populated(
        self,
        mapper: FaultReportingMapper,
    ):
        section = make_section(id="s1", tables=[])
        origins: dict[str, FieldOrigin] = {}
        _, origins = mapper.map([section], origins)
        assert "faultReporting.faultEntries" in origins


# ═══════════════════════════════════════════════════════════════════════
#  Table-based extraction
# ═══════════════════════════════════════════════════════════════════════


class TestTableExtraction:
    def test_lru_table_produces_detection_and_repair(
        self,
        mapper: FaultReportingMapper,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        """When table classified as LRU_LIST, LRU extraction populates
        detection_info and locate_and_repair."""
        fake_rules.table_by_headers_value = TableType.LRU_LIST
        fake_llm.lru_sru_results = [
            LruSruExtraction(
                name="Hydraulic Pump", short_name="HYD",
                ident_number="29-10", is_lru=True, confidence=0.95,
            ),
        ]

        table = make_table(
            id="t1", headers=["Part", "LRU Name"],
            rows=[["29-10", "Hydraulic Pump"]],
        )
        section = make_section(id="s1", tables=[table])
        content, _ = mapper.map([section], {})

        assert len(content.fault_entries) == 1
        entry = content.fault_entries[0]
        assert entry.detection_info is not None
        assert len(entry.detection_info.detected_lru_item.lrus) == 1
        assert entry.detection_info.detected_lru_item.lrus[0].name == "Hydraulic Pump"
        assert entry.locate_and_repair is not None

    def test_mixed_lru_sru_extraction(
        self,
        mapper: FaultReportingMapper,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.table_by_headers_value = TableType.LRU_LIST
        fake_llm.lru_sru_results = [
            LruSruExtraction(
                name="Pump", is_lru=True, confidence=0.9,
            ),
            LruSruExtraction(
                name="Seal Kit", is_lru=False, confidence=0.8,
            ),
        ]

        table = make_table(id="t1", headers=["Part"])
        section = make_section(id="s1", tables=[table])
        content, _ = mapper.map([section], {})

        entry = content.fault_entries[0]
        assert entry.detection_info is not None
        lru_item = entry.detection_info.detected_lru_item
        assert len(lru_item.lrus) == 1
        assert lru_item.detected_sru_item is not None
        assert len(lru_item.detected_sru_item.srus) == 1

    def test_unclassified_table_no_extraction(
        self,
        mapper: FaultReportingMapper,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        """Tables classified as GENERAL/UNKNOWN don't trigger extraction."""
        fake_rules.table_by_headers_value = None  # inconclusive rule
        fake_llm.table_classification_result = TableClassification(
            role=TableType.GENERAL,
            confidence=0.90,
            reasoning="general table",
        )
        fake_llm.lru_sru_results = []  # no extractions anyway

        table = make_table(id="t1", headers=["Notes"])
        section = make_section(id="s1", tables=[table])
        content, _ = mapper.map([section], {})

        entry = content.fault_entries[0]
        # No tables matched FAULT_CODE_TABLE / LRU_LIST / SRU_LIST
        assert entry.detection_info is None
        assert entry.locate_and_repair is None


# ═══════════════════════════════════════════════════════════════════════
#  Fault description (LLM + RULE)
# ═══════════════════════════════════════════════════════════════════════


class TestFaultDescription:
    def test_llm_description_with_details(
        self,
        mapper: FaultReportingMapper,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.table_by_headers_value = TableType.LRU_LIST
        fake_llm.description_results = [
            FaultDescriptionInterpretation(
                description="Hydraulic pressure loss",
                system_name="Hydraulic",
                fault_code_suggestion="FC-HYD-001",
                fault_equipment="Pump Assembly",
                fault_message="Low pressure alarm",
                confidence=0.92,
            ),
        ]
        fake_llm.lru_sru_results = [
            LruSruExtraction(name="Pump", is_lru=True, confidence=0.9),
        ]

        table = make_table(id="t1", headers=["Part"])
        section = make_section(id="s1", tables=[table])
        content, origins = mapper.map([section], {})

        entry = content.fault_entries[0]
        assert entry.fault_descr.descr == "Hydraulic pressure loss"
        assert entry.fault_descr.detailed is not None
        assert entry.fault_descr.detailed.system_name == "Hydraulic"
        assert entry.fault_code == "FC-HYD-001"

    def test_llm_below_threshold_falls_back_to_direct(
        self,
        mapper: FaultReportingMapper,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.table_by_headers_value = TableType.LRU_LIST
        fake_rules.threshold_value = 0.80
        fake_llm.description_results = [
            FaultDescriptionInterpretation(
                description="Maybe something",
                confidence=0.40,  # below threshold
            ),
        ]
        fake_llm.lru_sru_results = [
            LruSruExtraction(name="Pump", is_lru=True, confidence=0.9),
        ]

        table = make_table(id="t1", headers=["Part"])
        section = make_section(
            id="s1", section_title="Pump Failure", tables=[table],
        )
        content, _ = mapper.map([section], {})

        entry = content.fault_entries[0]
        # Falls back to section title
        assert entry.fault_descr.descr == "Pump Failure"
        assert entry.fault_descr.detailed is None
        # Uses rules engine for fault code
        assert entry.fault_code == fake_rules.fault_code_value


# ═══════════════════════════════════════════════════════════════════════
#  Schematic correlation
# ═══════════════════════════════════════════════════════════════════════


class TestSchematicCorrelation:
    def test_schematics_added_to_common_info_figures(
        self,
        mapper: FaultReportingMapper,
    ):
        sch = make_schematic(
            id="sch-1",
            components=[make_schematic_component(name="Fault Reporting")],
            page_number=1,
        )
        section = make_section(
            id="s1",
            section_title="Fault Reporting",
            tables=[],
            page_numbers=[1, 2],
        )
        content, _ = mapper.map([section], {}, schematics=[sch])

        assert content.common_info is not None
        assert len(content.common_info.figures) >= 1

    def test_no_schematics_no_figures(
        self,
        mapper: FaultReportingMapper,
    ):
        section = make_section(id="s1", tables=[])
        content, _ = mapper.map([section], {}, schematics=None)
        # figures list exists but may be empty
        assert content.common_info is not None
        assert len(content.common_info.figures) == 0
