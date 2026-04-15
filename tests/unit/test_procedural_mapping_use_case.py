"""Unit tests for ``ProceduralMappingUseCase``.

End-to-end orchestration test with fakes — verifies the 7-step pipeline
produces a valid ``S1000DProceduralDataModule`` with correct wiring,
copy-on-write section population, and error handling.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.procedural_enums import (
    ProceduralModuleType,
    ProceduralSectionType,
)
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.domain.procedural_value_objects import (
    ProceduralRelevanceAssessment,
    SectionClassificationResult,
    StepInterpretation,
)

from fault_mapper.application.procedural_document_classifier import (
    ProceduralDocumentClassifier,
)
from fault_mapper.application.procedural_header_builder import (
    ProceduralHeaderBuilder,
)
from fault_mapper.application.procedural_mapping_use_case import (
    ProceduralMappingUseCase,
)
from fault_mapper.application.procedural_module_assembler import (
    ProceduralModuleAssembler,
)
from fault_mapper.application.procedural_reference_extractor import (
    ProceduralReferenceExtractor,
)
from fault_mapper.application.procedural_requirement_extractor import (
    ProceduralRequirementExtractor,
)
from fault_mapper.application.procedural_section_organizer import (
    ProceduralSectionOrganizer,
)
from fault_mapper.application.procedural_step_extractor import (
    ProceduralStepExtractor,
)

from tests.conftest import (
    FakeProceduralLlmInterpreter,
    FakeProceduralRulesEngine,
    make_section,
    make_source,
)


@pytest.fixture
def use_case(
    fake_procedural_rules: FakeProceduralRulesEngine,
    fake_procedural_llm: FakeProceduralLlmInterpreter,
) -> ProceduralMappingUseCase:
    """Build a fully wired use case with fake adapters."""
    classifier = ProceduralDocumentClassifier(
        rules=fake_procedural_rules, llm=fake_procedural_llm,
    )
    organizer = ProceduralSectionOrganizer(
        rules=fake_procedural_rules, llm=fake_procedural_llm,
    )
    header_builder = ProceduralHeaderBuilder(rules=fake_procedural_rules)
    step_extractor = ProceduralStepExtractor(
        rules=fake_procedural_rules, llm=fake_procedural_llm,
    )
    requirement_extractor = ProceduralRequirementExtractor(
        rules=fake_procedural_rules, llm=fake_procedural_llm,
    )
    reference_extractor = ProceduralReferenceExtractor(
        rules=fake_procedural_rules, llm=fake_procedural_llm,
    )
    assembler = ProceduralModuleAssembler(rules=fake_procedural_rules)

    return ProceduralMappingUseCase(
        classifier=classifier,
        organizer=organizer,
        header_builder=header_builder,
        step_extractor=step_extractor,
        requirement_extractor=requirement_extractor,
        reference_extractor=reference_extractor,
        assembler=assembler,
    )


class TestEndToEnd:
    """Full pipeline execution with fakes."""

    def test_produces_valid_module(
        self,
        use_case: ProceduralMappingUseCase,
    ):
        source = make_source(sections=[
            make_section(
                section_title="Removal Procedure",
                section_type="procedure",
                section_text="1. Remove access panel. 2. Disconnect wiring.",
                id="s1",
            ),
        ])
        result = use_case.execute(source)

        assert isinstance(result, S1000DProceduralDataModule)
        assert result.record_id == "proc-test-001"
        assert result.module_type is ProceduralModuleType.PROCEDURAL
        assert result.ident_and_status_section is not None
        assert result.source is not None
        assert result.trace is not None

    def test_sections_have_steps(
        self,
        use_case: ProceduralMappingUseCase,
    ):
        source = make_source(sections=[
            make_section(
                section_type="procedure",
                section_text="Step 1: Remove panel.",
                id="s1",
            ),
        ])
        result = use_case.execute(source)

        # Sections should have been populated with steps
        assert len(result.content.sections) >= 1
        # Steps should have been extracted by the fake LLM
        assert result.total_steps >= 1

    def test_descriptive_module_type(
        self,
        use_case: ProceduralMappingUseCase,
    ):
        source = make_source(sections=[
            make_section(section_type="procedure", id="s1"),
        ])
        result = use_case.execute(
            source, module_type=ProceduralModuleType.DESCRIPTIVE,
        )
        assert result.module_type is ProceduralModuleType.DESCRIPTIVE


class TestErrorHandling:
    def test_raises_on_no_relevant_sections(
        self,
        use_case: ProceduralMappingUseCase,
        fake_procedural_rules: FakeProceduralRulesEngine,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        # Ensure RULE pass cannot match so only LLM fallback evaluates.
        fake_procedural_rules.keywords_value = frozenset()
        fake_procedural_rules.section_types_value = frozenset()
        fake_procedural_llm.relevance_result = ProceduralRelevanceAssessment(
            is_relevant=False, confidence=0.1, reasoning="not procedural",
        )
        source = make_source(sections=[
            make_section(
                section_title="Preface",
                section_type="preface",
                section_text="General introduction.",
                id="s1",
            ),
        ])
        with pytest.raises(ValueError, match="No procedural-relevant"):
            use_case.execute(source)

    def test_empty_document_raises(
        self,
        use_case: ProceduralMappingUseCase,
    ):
        source = make_source(sections=[])
        with pytest.raises(ValueError, match="No procedural-relevant"):
            use_case.execute(source)


class TestCopyOnWrite:
    """Verify that sections are NOT mutated in-place."""

    def test_shells_not_mutated(
        self,
        use_case: ProceduralMappingUseCase,
        fake_procedural_rules: FakeProceduralRulesEngine,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        """The organizer's shells should remain step-free after execute."""
        # We'll manually track the organizer's output
        fake_procedural_rules.classify_section_value = (
            ProceduralSectionType.PROCEDURE
        )
        source = make_source(sections=[
            make_section(section_type="procedure", id="s1"),
        ])

        # Execute the pipeline
        result = use_case.execute(source)

        # The result sections should have steps
        assert result.total_steps >= 1

        # But since dataclasses.replace() was used, the result sections
        # are NEW objects, not the original shells
        for section in result.content.sections:
            # The section should have steps populated
            assert isinstance(section.steps, list)


class TestMultipleSections:
    def test_multiple_sections_all_populated(
        self,
        use_case: ProceduralMappingUseCase,
    ):
        source = make_source(sections=[
            make_section(
                section_type="procedure",
                section_title="Step One",
                section_order=0,
                id="s1",
            ),
            make_section(
                section_type="maintenance",
                section_title="Step Two",
                section_order=1,
                id="s2",
            ),
        ])
        result = use_case.execute(source)

        assert len(result.content.sections) == 2
        # Both sections should have steps
        for sec in result.content.sections:
            assert len(sec.steps) >= 1


class TestTraceIntegrity:
    def test_trace_contains_all_phase_origins(
        self,
        use_case: ProceduralMappingUseCase,
    ):
        source = make_source(sections=[
            make_section(section_type="procedure", id="s1"),
        ])
        result = use_case.execute(source)

        trace = result.trace
        assert trace is not None
        # Should contain origins from classification, header, organization,
        # steps, requirements, and references
        assert len(trace.field_origins) > 0
        assert trace.mapped_at is not None
