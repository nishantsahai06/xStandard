"""Unit tests for ``ProceduralModuleAssembler``.

Pure RULE assembly — no LLM.  Tests verify that the assembler wires
pre-computed pieces into the root ``S1000DProceduralDataModule``
aggregate with correct provenance, classification, and trust metadata.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import (
    ClassificationMethod,
    MappingStrategy,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import (
    ProceduralHeader,
    ProceduralSection,
    ProceduralRequirementItem,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.value_objects import FieldOrigin

from fault_mapper.application.procedural_module_assembler import (
    ProceduralModuleAssembler,
)

from tests.conftest import (
    FakeMappingReviewPolicy,
    FakeProceduralRulesEngine,
    make_dm_code,
    make_field_origin,
    make_issue_date,
    make_issue_info,
    make_language,
    make_section,
    make_source,
)


def _make_procedural_header() -> ProceduralHeader:
    """Build a minimal procedural header for testing."""
    from fault_mapper.domain.value_objects import DmTitle
    return ProceduralHeader(
        dm_code=make_dm_code(info_code="200"),
        language=make_language(),
        issue_info=make_issue_info(),
        issue_date=make_issue_date(),
        dm_title=DmTitle(tech_name="Test Procedure", info_name="Procedure"),
    )


@pytest.fixture
def assembler(
    fake_procedural_rules: FakeProceduralRulesEngine,
) -> ProceduralModuleAssembler:
    return ProceduralModuleAssembler(rules=fake_procedural_rules)


@pytest.fixture
def assembler_with_review(
    fake_procedural_rules: FakeProceduralRulesEngine,
    fake_review_policy: FakeMappingReviewPolicy,
) -> ProceduralModuleAssembler:
    return ProceduralModuleAssembler(
        rules=fake_procedural_rules,
        review_policy=fake_review_policy,
    )


def _call_assemble(
    assembler: ProceduralModuleAssembler,
    module_type: ProceduralModuleType = ProceduralModuleType.PROCEDURAL,
) -> S1000DProceduralDataModule:
    """Helper to call assemble with minimal valid args."""
    source = make_source()
    header = _make_procedural_header()
    sections = [ProceduralSection(section_id="sec-1", title="Main Procedure")]
    requirements = [
        ProceduralRequirementItem(requirement_type="equipment", name="Wrench"),
    ]
    all_origins = {
        "header.dm_code": make_field_origin(),
        "section_type.s1": make_field_origin(),
    }

    return assembler.assemble(
        source=source,
        module_type=module_type,
        header=header,
        sections=sections,
        requirements=requirements,
        refs=[],
        figure_refs=[],
        table_refs=[],
        all_origins=all_origins,
        selected_sections=[make_section()],
    )


class TestProceduralModuleAssembler:
    def test_returns_complete_module(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert isinstance(result, S1000DProceduralDataModule)
        assert result.record_id == "proc-test-001"
        assert result.module_type is ProceduralModuleType.PROCEDURAL
        assert result.ident_and_status_section is not None
        assert len(result.content.sections) == 1
        assert len(result.content.preliminary_requirements) == 1

    def test_descriptive_module_type(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(
            assembler, module_type=ProceduralModuleType.DESCRIPTIVE,
        )
        assert result.module_type is ProceduralModuleType.DESCRIPTIVE

    def test_provenance_populated(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.source is not None
        assert result.source.source_document_id == "doc-001"
        assert len(result.source.source_section_ids) >= 1

    def test_trace_merges_all_origins(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.trace is not None
        assert "header.dm_code" in result.trace.field_origins
        assert "section_type.s1" in result.trace.field_origins

    def test_lineage_populated(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.lineage is not None
        assert result.lineage.mapped_by == "fault_mapper.procedural"
        assert result.lineage.mapping_ruleset_version == "1.0.0"

    def test_validation_defaults_to_pending(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.validation is not None
        assert result.validation.status == ValidationStatus.PENDING

    def test_review_status_defaults_not_reviewed_without_policy(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.review_status == ReviewStatus.NOT_REVIEWED

    def test_review_policy_delegates_when_present(
        self,
        assembler_with_review: ProceduralModuleAssembler,
        fake_review_policy: FakeMappingReviewPolicy,
    ):
        result = _call_assemble(assembler_with_review)
        assert result.review_status == ReviewStatus.APPROVED
        assert len(fake_review_policy.calls) == 1

    def test_classification_rules_only(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(assembler)
        cls = result.classification
        assert cls is not None
        assert cls.method == ClassificationMethod.RULES
        assert cls.confidence > 0

    def test_classification_mixed_with_llm_origins(
        self,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        asm = ProceduralModuleAssembler(rules=fake_procedural_rules)
        source = make_source()
        header = _make_procedural_header()

        llm_origin = make_field_origin(
            strategy=MappingStrategy.LLM, confidence=0.85,
        )

        result = asm.assemble(
            source=source,
            module_type=ProceduralModuleType.PROCEDURAL,
            header=header,
            sections=[ProceduralSection(section_id="s1")],
            requirements=[],
            refs=[],
            figure_refs=[],
            table_refs=[],
            all_origins={
                "header.dm_code": make_field_origin(),
                "content.llm": llm_origin,
            },
            selected_sections=[make_section()],
        )
        assert result.classification is not None
        assert result.classification.method == ClassificationMethod.LLM_RULES

    def test_trace_warns_on_llm_fields(
        self,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        asm = ProceduralModuleAssembler(rules=fake_procedural_rules)
        source = make_source()
        header = _make_procedural_header()

        llm_origin = make_field_origin(
            strategy=MappingStrategy.LLM, confidence=0.85,
        )

        result = asm.assemble(
            source=source,
            module_type=ProceduralModuleType.PROCEDURAL,
            header=header,
            sections=[],
            requirements=[],
            refs=[],
            figure_refs=[],
            table_refs=[],
            all_origins={"x": llm_origin},
            selected_sections=[make_section()],
        )
        assert result.trace is not None
        assert any("LLM" in w for w in result.trace.warnings)

    def test_trace_warns_on_low_confidence(
        self,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        asm = ProceduralModuleAssembler(rules=fake_procedural_rules)
        source = make_source()
        header = _make_procedural_header()

        low_origin = make_field_origin(confidence=0.3)

        result = asm.assemble(
            source=source,
            module_type=ProceduralModuleType.PROCEDURAL,
            header=header,
            sections=[],
            requirements=[],
            refs=[],
            figure_refs=[],
            table_refs=[],
            all_origins={"low_field": low_origin},
            selected_sections=[make_section()],
        )
        assert result.trace is not None
        assert any("below 0.7" in w for w in result.trace.warnings)

    def test_mapping_version_set(
        self,
        assembler: ProceduralModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.mapping_version == "1.0.0"
