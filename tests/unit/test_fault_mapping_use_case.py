"""Integration-level unit test for ``FaultMappingUseCase``.

Full pipeline with all fakes — verifies the orchestration sequence:
select → route → build header → map content → assemble.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import (
    FaultMode,
    MappingStrategy,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.models import S1000DFaultDataModule

from fault_mapper.application.fault_section_selector import FaultSectionSelector
from fault_mapper.application.fault_mode_router import FaultModeRouter
from fault_mapper.application.fault_header_builder import FaultHeaderBuilder
from fault_mapper.application.fault_reporting_mapper import FaultReportingMapper
from fault_mapper.application.fault_isolation_mapper import FaultIsolationMapper
from fault_mapper.application.fault_module_assembler import FaultModuleAssembler
from fault_mapper.application.fault_table_classifier import FaultTableClassifier
from fault_mapper.application.fault_schematic_correlator import (
    FaultSchematicCorrelator,
)
from fault_mapper.application.fault_mapping_use_case import FaultMappingUseCase

from tests.conftest import (
    FakeLlmInterpreter,
    FakeMappingReviewPolicy,
    FakeRulesEngine,
    make_section,
    make_source,
)


def _build_use_case(
    fake_llm: FakeLlmInterpreter,
    fake_rules: FakeRulesEngine,
    fake_review: FakeMappingReviewPolicy | None = None,
) -> FaultMappingUseCase:
    """Wire up the full pipeline with fakes."""
    selector = FaultSectionSelector(rules=fake_rules, llm=fake_llm)
    router = FaultModeRouter(rules=fake_rules, llm=fake_llm)
    header_builder = FaultHeaderBuilder(rules=fake_rules)
    table_cls = FaultTableClassifier(rules=fake_rules, llm=fake_llm)
    correlator = FaultSchematicCorrelator(llm=fake_llm, rules=fake_rules)
    reporting_mapper = FaultReportingMapper(
        llm=fake_llm,
        rules=fake_rules,
        table_classifier=table_cls,
        schematic_correlator=correlator,
    )
    isolation_mapper = FaultIsolationMapper(llm=fake_llm, rules=fake_rules)
    assembler = FaultModuleAssembler(
        rules=fake_rules,
        review_policy=fake_review,
    )

    return FaultMappingUseCase(
        section_selector=selector,
        mode_router=router,
        header_builder=header_builder,
        reporting_mapper=reporting_mapper,
        isolation_mapper=isolation_mapper,
        assembler=assembler,
    )


class TestFaultMappingUseCaseReporting:
    """Full pipeline producing a fault-reporting module."""

    def test_happy_path_reporting(
        self,
        fake_llm: FakeLlmInterpreter,
        fake_rules: FakeRulesEngine,
    ):
        # Default fake_rules sections types include "fault_reporting"
        # Default fake_llm mode → FAULT_REPORTING
        fake_rules.mode_by_structure_value = FaultMode.FAULT_REPORTING
        source = make_source(sections=[
            make_section(
                section_type="fault_reporting",
                section_title="Engine Fault Report",
                id="sec-1",
            ),
        ])

        use_case = _build_use_case(fake_llm, fake_rules)
        result = use_case.execute(source)

        assert isinstance(result, S1000DFaultDataModule)
        assert result.mode is FaultMode.FAULT_REPORTING
        assert result.header is not None
        assert result.content.fault_reporting is not None
        assert result.content.fault_isolation is None
        assert result.provenance is not None
        assert result.trace is not None
        assert result.validation_status == ValidationStatus.PENDING
        assert result.record_id == "rec-test-001"

    def test_with_review_policy(
        self,
        fake_llm: FakeLlmInterpreter,
        fake_rules: FakeRulesEngine,
        fake_review_policy: FakeMappingReviewPolicy,
    ):
        fake_rules.mode_by_structure_value = FaultMode.FAULT_REPORTING
        source = make_source(sections=[
            make_section(section_type="fault_reporting", id="sec-1"),
        ])

        use_case = _build_use_case(fake_llm, fake_rules, fake_review_policy)
        result = use_case.execute(source)
        assert result.review_status == ReviewStatus.APPROVED


class TestFaultMappingUseCaseIsolation:
    """Full pipeline producing a fault-isolation module."""

    def test_happy_path_isolation(
        self,
        fake_llm: FakeLlmInterpreter,
        fake_rules: FakeRulesEngine,
    ):
        fake_rules.mode_by_structure_value = FaultMode.FAULT_ISOLATION
        source = make_source(sections=[
            make_section(
                section_type="fault_isolation",
                section_title="Troubleshooting",
                section_text="Step 1: Check hydraulic pressure.",
                id="sec-1",
            ),
        ])

        use_case = _build_use_case(fake_llm, fake_rules)
        result = use_case.execute(source)

        assert result.mode is FaultMode.FAULT_ISOLATION
        assert result.content.fault_isolation is not None
        assert result.content.fault_reporting is None
        assert len(result.content.fault_isolation.fault_isolation_steps) >= 1


class TestFaultMappingUseCaseEdgeCases:
    def test_no_relevant_sections_raises(
        self,
        fake_llm: FakeLlmInterpreter,
        fake_rules: FakeRulesEngine,
    ):
        from fault_mapper.domain.value_objects import FaultRelevanceAssessment

        # No section-type match, no keyword match, LLM says not relevant
        fake_llm.relevance_result = FaultRelevanceAssessment(
            is_relevant=False, confidence=0.1, reasoning="irrelevant",
        )
        source = make_source(sections=[
            make_section(
                section_type="preface",
                section_title="Introduction",
                section_text="Welcome to this manual.",
                id="sec-1",
            ),
        ])

        use_case = _build_use_case(fake_llm, fake_rules)
        with pytest.raises(ValueError, match="No fault-relevant sections"):
            use_case.execute(source)

    def test_empty_document_raises(
        self,
        fake_llm: FakeLlmInterpreter,
        fake_rules: FakeRulesEngine,
    ):
        source = make_source(sections=[])
        use_case = _build_use_case(fake_llm, fake_rules)
        with pytest.raises(ValueError, match="No fault-relevant sections"):
            use_case.execute(source)

    def test_provenance_tracks_section_and_chunk_ids(
        self,
        fake_llm: FakeLlmInterpreter,
        fake_rules: FakeRulesEngine,
    ):
        fake_rules.mode_by_structure_value = FaultMode.FAULT_REPORTING
        source = make_source(sections=[
            make_section(
                section_type="fault_reporting",
                id="sec-A",
            ),
        ])

        use_case = _build_use_case(fake_llm, fake_rules)
        result = use_case.execute(source)

        prov = result.provenance
        assert prov is not None
        assert "sec-A" in prov.source_section_ids
        assert len(prov.source_chunk_ids) >= 1
