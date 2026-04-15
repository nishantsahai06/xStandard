"""Unit tests for ``FaultModuleAssembler``.

Pure RULE assembly — no LLM.  Tests verify that the assembler wires
pre-computed pieces into the root ``S1000DFaultDataModule`` aggregate
with correct provenance, classification, and default trust metadata.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import (
    ClassificationMethod,
    FaultMode,
    MappingStrategy,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    FaultReportingContent,
    FaultIsolationContent,
    S1000DFaultDataModule,
)
from fault_mapper.domain.value_objects import FieldOrigin

from fault_mapper.application.fault_module_assembler import FaultModuleAssembler

from tests.conftest import (
    FakeMappingReviewPolicy,
    FakeRulesEngine,
    make_field_origin,
    make_header,
    make_section,
    make_source,
)


@pytest.fixture
def assembler(
    fake_rules: FakeRulesEngine,
) -> FaultModuleAssembler:
    return FaultModuleAssembler(rules=fake_rules)


@pytest.fixture
def assembler_with_review(
    fake_rules: FakeRulesEngine,
    fake_review_policy: FakeMappingReviewPolicy,
) -> FaultModuleAssembler:
    return FaultModuleAssembler(
        rules=fake_rules,
        review_policy=fake_review_policy,
    )


def _call_assemble(assembler, mode=FaultMode.FAULT_REPORTING):
    """Helper to call assemble with minimal valid args."""
    source = make_source()
    sections = [make_section()]
    header = make_header()
    reporting = FaultReportingContent() if mode is FaultMode.FAULT_REPORTING else None
    isolation = FaultIsolationContent() if mode is FaultMode.FAULT_ISOLATION else None
    mode_origin = make_field_origin(strategy=MappingStrategy.RULE)

    return assembler.assemble(
        source=source,
        mode=mode,
        header=header,
        fault_reporting=reporting,
        fault_isolation=isolation,
        selected_sections=sections,
        header_origins={"header.dm_code": make_field_origin()},
        content_origins={"content.entry": make_field_origin()},
        selection_origins={"sel.sec1": make_field_origin()},
        mode_origin=mode_origin,
    )


class TestFaultModuleAssembler:
    def test_returns_complete_module(
        self, assembler: FaultModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert isinstance(result, S1000DFaultDataModule)
        assert result.record_id == "rec-test-001"
        assert result.mode is FaultMode.FAULT_REPORTING
        assert result.header is not None
        assert result.content.fault_reporting is not None
        assert result.content.fault_isolation is None

    def test_isolation_mode_wiring(
        self, assembler: FaultModuleAssembler,
    ):
        result = _call_assemble(assembler, mode=FaultMode.FAULT_ISOLATION)
        assert result.mode is FaultMode.FAULT_ISOLATION
        assert result.content.fault_isolation is not None
        assert result.content.fault_reporting is None

    def test_provenance_populated(
        self, assembler: FaultModuleAssembler,
    ):
        result = _call_assemble(assembler)
        prov = result.provenance
        assert prov is not None
        assert prov.source_document_id == "doc-001"
        assert len(prov.source_section_ids) >= 1

    def test_trace_merges_all_origins(
        self, assembler: FaultModuleAssembler,
    ):
        result = _call_assemble(assembler)
        trace = result.trace
        assert trace is not None
        # header + content + selection + mode
        assert "header.dm_code" in trace.field_origins
        assert "content.entry" in trace.field_origins
        assert "sel.sec1" in trace.field_origins
        assert "mode" in trace.field_origins

    def test_validation_status_defaults_to_pending(
        self, assembler: FaultModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.validation_status == ValidationStatus.PENDING

    def test_review_status_defaults_not_reviewed_without_policy(
        self, assembler: FaultModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.review_status == ReviewStatus.NOT_REVIEWED

    def test_review_policy_delegates_when_present(
        self,
        assembler_with_review: FaultModuleAssembler,
        fake_review_policy: FakeMappingReviewPolicy,
    ):
        result = _call_assemble(assembler_with_review)
        assert result.review_status == ReviewStatus.APPROVED
        assert len(fake_review_policy.calls) == 1

    def test_classification_method_rules_only(
        self, assembler: FaultModuleAssembler,
    ):
        result = _call_assemble(assembler)
        cls = result.classification
        assert cls is not None
        assert cls.method == ClassificationMethod.RULES
        assert cls.confidence > 0

    def test_classification_mixed_with_llm_origins(
        self, fake_rules: FakeRulesEngine,
    ):
        asm = FaultModuleAssembler(rules=fake_rules)
        source = make_source()
        sections = [make_section()]
        header = make_header()

        llm_origin = make_field_origin(
            strategy=MappingStrategy.LLM, confidence=0.85,
        )

        result = asm.assemble(
            source=source,
            mode=FaultMode.FAULT_REPORTING,
            header=header,
            fault_reporting=FaultReportingContent(),
            fault_isolation=None,
            selected_sections=sections,
            header_origins={"header.dm_code": make_field_origin()},
            content_origins={"content.llm": llm_origin},
            selection_origins={},
            mode_origin=make_field_origin(),
        )
        assert result.classification is not None
        assert result.classification.method == ClassificationMethod.LLM_RULES

    def test_trace_warns_on_llm_fields(
        self, fake_rules: FakeRulesEngine,
    ):
        asm = FaultModuleAssembler(rules=fake_rules)
        source = make_source()
        sections = [make_section()]
        header = make_header()

        llm_origin = make_field_origin(
            strategy=MappingStrategy.LLM, confidence=0.85,
        )

        result = asm.assemble(
            source=source,
            mode=FaultMode.FAULT_REPORTING,
            header=header,
            fault_reporting=FaultReportingContent(),
            fault_isolation=None,
            selected_sections=sections,
            header_origins={},
            content_origins={"x": llm_origin},
            selection_origins={},
            mode_origin=make_field_origin(),
        )
        assert result.trace is not None
        assert any("LLM" in w for w in result.trace.warnings)

    def test_trace_warns_on_low_confidence(
        self, fake_rules: FakeRulesEngine,
    ):
        asm = FaultModuleAssembler(rules=fake_rules)
        source = make_source()
        sections = [make_section()]
        header = make_header()

        low_origin = make_field_origin(confidence=0.3)

        result = asm.assemble(
            source=source,
            mode=FaultMode.FAULT_REPORTING,
            header=header,
            fault_reporting=FaultReportingContent(),
            fault_isolation=None,
            selected_sections=sections,
            header_origins={"low_field": low_origin},
            content_origins={},
            selection_origins={},
            mode_origin=make_field_origin(),
        )
        assert result.trace is not None
        assert any("below 0.7" in w for w in result.trace.warnings)

    def test_mapping_version_set(
        self, assembler: FaultModuleAssembler,
    ):
        result = _call_assemble(assembler)
        assert result.mapping_version == "1.0.0"
