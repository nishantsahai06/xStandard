"""Procedural validation-layer fixture builders — canonical-schema-aligned.

These builders produce ``S1000DProceduralDataModule`` instances whose
serialised form passes the canonical procedural JSON Schema.

The canonical schema requires:
  - source with pipelineDocumentId (^doc_...), fileName, fileType, sourcePath, metadata
  - identAndStatusSection with dmCode (including learnCode, learnEventCode),
    language, issueInfo, issueDate, dmTitle (techName+infoName required),
    securityClassification (enum), responsiblePartnerCompany (object),
    origin (isExtracted, isHumanReviewed)
  - content.sections[].sectionType from canonical enum
  - content.sections[].pageNumbers (minItems: 1)
  - validation (schemaValid, businessRuleValid, status from canonical enum)
  - lineage (mappedBy, mappedAt, mappingRulesetVersion, sourceSections)
"""

from __future__ import annotations

from typing import Any

from fault_mapper.domain.enums import (
    ClassificationMethod,
    MappingStrategy,
    ReviewStatus,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    Classification,
    FigureRef,
    NoteLike,
    Provenance,
)
from fault_mapper.domain.procedural_enums import (
    ActionType,
    ProceduralModuleType,
    ProceduralSectionType,
    SecurityClassification,
)
from fault_mapper.domain.procedural_models import (
    ProceduralContent,
    ProceduralHeader,
    ProceduralLineage,
    ProceduralReference,
    ProceduralRequirementItem,
    ProceduralSection,
    ProceduralStep,
    ProceduralTableRef,
    ProceduralValidationResults,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.procedural_value_objects import (
    DataOrigin,
    ProceduralConfidence,
    ResponsiblePartnerCompany,
    SourceSectionRef,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    FieldOrigin,
    IssueDate,
    IssueInfo,
    Language,
    MappingTrace,
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)


# ═══════════════════════════════════════════════════════════════════════
#  SCHEMA-VALID DM CODE
# ═══════════════════════════════════════════════════════════════════════


def make_procedural_dm_code(**overrides: Any) -> DmCode:
    """DM code that satisfies canonical schema patterns."""
    defaults = dict(
        model_ident_code="TESTAC",
        system_diff_code="A",
        system_code="29",
        sub_system_code="00",
        sub_sub_system_code="00",
        assy_code="00",
        disassy_code="00",
        disassy_code_variant="A",
        info_code="200",
        info_code_variant="A",
        item_location_code="A",
        learn_code=None,
        learn_event_code=None,
    )
    defaults.update(overrides)
    return DmCode(**defaults)


def make_procedural_header(**overrides: Any) -> ProceduralHeader:
    """Fully canonical-schema-valid procedural header.

    Note: domain stores security_classification and
    responsible_partner_company as simple strings.  The serializer
    bridges to canonical shapes.
    """
    defaults = dict(
        dm_code=make_procedural_dm_code(),
        language=Language(language_iso_code="en", country_iso_code="US"),
        issue_info=IssueInfo(issue_number="001", in_work="00"),
        issue_date=IssueDate(year="2026", month="04", day="16"),
        dm_title=DmTitle(
            tech_name="Maintenance Procedure",
            info_name="Engine Oil Change",
        ),
        security_classification=SecurityClassification.UNCLASSIFIED,
        responsible_partner_company=ResponsiblePartnerCompany(
            enterprise_code="LEXX",
            enterprise_name="LEXX Aerospace",
        ),
        origin=DataOrigin(is_extracted=True, is_human_reviewed=False),
    )
    defaults.update(overrides)
    return ProceduralHeader(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  CONTENT BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_procedural_step(**overrides: Any) -> ProceduralStep:
    """Minimal valid procedural step."""
    defaults = dict(
        step_id="step-1",
        step_number="1",
        text="Remove the oil drain plug.",
        action_type=ActionType.REMOVE,
    )
    defaults.update(overrides)
    return ProceduralStep(**defaults)


def make_procedural_section(**overrides: Any) -> ProceduralSection:
    """Minimal valid section with one step and page_numbers.

    Uses PROCEDURE section type which maps to canonical 'mainProcedure'.
    """
    defaults = dict(
        section_id="sec-1",
        title="Oil Drain Procedure",
        section_order=1,
        section_type=ProceduralSectionType.PROCEDURE,
        level=1,
        page_numbers=[1],
        steps=[make_procedural_step()],
    )
    defaults.update(overrides)
    return ProceduralSection(**defaults)


def make_procedural_content(**overrides: Any) -> ProceduralContent:
    """Content with one section containing one step."""
    defaults = dict(sections=[make_procedural_section()])
    defaults.update(overrides)
    return ProceduralContent(**defaults)


def make_procedural_lineage(**overrides: Any) -> ProceduralLineage:
    """Minimal valid lineage (domain shape).

    mapping_method='rules' maps to canonical 'rules-only'.
    """
    defaults = dict(
        mapped_by="xstandard-procedural-mapper",
        mapped_at="2026-04-16T12:00:00+00:00",
        mapping_ruleset_version="1.0.0",
        mapping_method="rules",
        source_sections=[SourceSectionRef(section_id="sec-1", page_numbers=(1,))],
        confidence=ProceduralConfidence(
            document_classification=0.95,
            dm_code_inference=0.95,
            section_typing=0.95,
            step_segmentation=0.95,
        ),
    )
    defaults.update(overrides)
    return ProceduralLineage(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  WHOLE-MODULE BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_valid_procedural_module(
    **overrides: Any,
) -> S1000DProceduralDataModule:
    """Minimal module that passes BOTH schema and business-rule validation.

    The source Provenance uses a doc_ prefixed ID so the serializer
    produces a valid pipelineDocumentId.
    """
    defaults = dict(
        record_id="PROC-001",
        schema_version="1.0.0",
        module_type=ProceduralModuleType.PROCEDURAL,
        source=Provenance(
            source_document_id="doc_test-001",
            source_section_ids=["sec-1"],
        ),
        ident_and_status_section=make_procedural_header(),
        content=make_procedural_content(),
        lineage=make_procedural_lineage(),
    )
    defaults.update(overrides)
    return S1000DProceduralDataModule(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  INVALID / EDGE-CASE BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_procedural_module_missing_header() -> S1000DProceduralDataModule:
    """Module with ident_and_status_section=None → schema required error."""
    return S1000DProceduralDataModule(
        record_id="PROC-BAD-001",
        source=Provenance(
            source_document_id="doc_test-bad",
            source_section_ids=["sec-1"],
        ),
        ident_and_status_section=None,
        content=make_procedural_content(),
        lineage=make_procedural_lineage(),
    )


def make_procedural_module_empty_title() -> S1000DProceduralDataModule:
    """Module with empty techName → BIZ-P-001."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-001",
        ident_and_status_section=make_procedural_header(
            dm_title=DmTitle(tech_name="", info_name="Oil Change"),
        ),
    )


def make_procedural_module_no_info_name() -> S1000DProceduralDataModule:
    """Module with no infoName → BIZ-P-002 warning."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-002",
        ident_and_status_section=make_procedural_header(
            dm_title=DmTitle(
                tech_name="Maintenance Procedure", info_name=None,
            ),
        ),
    )


def make_procedural_module_unknown_model() -> S1000DProceduralDataModule:
    """Module with model_ident_code='UNKNOWN' → BIZ-P-003 warning."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-003",
        ident_and_status_section=make_procedural_header(
            dm_code=make_procedural_dm_code(model_ident_code="UNKNOWN"),
        ),
    )


def make_procedural_module_empty_step() -> S1000DProceduralDataModule:
    """Module with empty step text → BIZ-P-006."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-006",
        content=ProceduralContent(
            sections=[
                ProceduralSection(
                    section_id="sec-1",
                    title="Bad Section",
                    section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[1],
                    steps=[ProceduralStep(
                        step_id="s1", step_number="1", text="",
                    )],
                ),
            ],
        ),
    )


def make_procedural_module_no_lineage() -> S1000DProceduralDataModule:
    """Module with lineage=None → BIZ-P-008 warning."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-008",
        lineage=None,
    )


def make_procedural_module_bad_lineage_method() -> S1000DProceduralDataModule:
    """Module with unknown lineage.mapping_method → BIZ-P-009 warning."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-009",
        lineage=make_procedural_lineage(mapping_method="magic"),
    )


def make_procedural_module_duplicate_orders() -> S1000DProceduralDataModule:
    """Module with duplicate section_order values → BIZ-P-004."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-004",
        content=ProceduralContent(
            sections=[
                make_procedural_section(section_id="sec-1", section_order=1),
                make_procedural_section(
                    section_id="sec-2",
                    title="Second Section",
                    section_order=1,
                    steps=[make_procedural_step(
                        step_id="s2", step_number="2",
                    )],
                ),
            ],
        ),
    )


def make_procedural_module_empty_section() -> S1000DProceduralDataModule:
    """Module with section that has no steps or sub-sections → BIZ-P-005."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-005",
        content=ProceduralContent(
            sections=[
                ProceduralSection(
                    section_id="sec-1",
                    title="Empty Section",
                    section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[1],
                    steps=[],
                    sub_sections=[],
                ),
            ],
        ),
    )


def make_procedural_module_low_confidence() -> S1000DProceduralDataModule:
    """Module with low classification confidence → BIZ-P-013."""
    return make_valid_procedural_module(
        record_id="PROC-BIZ-013",
        classification=Classification(
            domain="S1000D",
            confidence=0.15,
            method=ClassificationMethod.LLM,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
#  TRACE / LLM-CONFIDENCE BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_procedural_trace_high_confidence() -> MappingTrace:
    """All fields mapped with high confidence (≥ 0.9)."""
    return MappingTrace(
        field_origins={
            "header.dm_code": FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path="section.title",
                confidence=0.95,
            ),
            "content.sections[0]": FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="section.chunks[0]",
                confidence=0.92,
            ),
        },
        warnings=[],
    )


def make_procedural_trace_low_confidence() -> MappingTrace:
    """Majority of LLM fields below 0.5 → BIZ-P-012 + gate concern."""
    return MappingTrace(
        field_origins={
            "header.dm_code": FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path="section.title",
                confidence=0.95,
            ),
            "content.sections[0].steps[0]": FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="section.chunks[0]",
                confidence=0.3,
            ),
            "content.sections[0].steps[1]": FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="section.chunks[1]",
                confidence=0.25,
            ),
            "content.sections[0].title": FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="section.chunks[2]",
                confidence=0.4,
            ),
        },
        warnings=["Low LLM confidence on multiple fields"],
    )


def make_procedural_module_with_low_confidence_trace() -> S1000DProceduralDataModule:
    """Module with low-confidence LLM trace → BIZ-P-012 + review concern."""
    return make_valid_procedural_module(
        record_id="PROC-LOW-CONF",
        trace=make_procedural_trace_low_confidence(),
    )


# ═══════════════════════════════════════════════════════════════════════
#  VALIDATION RESULT BUILDERS (reusable)
# ═══════════════════════════════════════════════════════════════════════


def make_procedural_validation_issue(
    code: str = "TEST-P-001",
    severity: ValidationSeverity = ValidationSeverity.WARNING,
    message: str = "Test procedural issue.",
    field_path: str | None = None,
    context: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        field_path=field_path,
        context=context,
    )


def make_procedural_clean_result() -> ModuleValidationResult:
    """Validation result with zero issues → APPROVED."""
    return ModuleValidationResult(
        structural_issues=[],
        business_issues=[],
        status=ValidationStatus.APPROVED,
    )


def make_procedural_error_result() -> ModuleValidationResult:
    """Validation result with structural errors → SCHEMA_FAILED."""
    return ModuleValidationResult(
        structural_issues=[
            make_procedural_validation_issue(
                code="SCHEMA-001",
                severity=ValidationSeverity.ERROR,
                message="Missing required property: 'identAndStatusSection'",
            ),
        ],
        business_issues=[],
        status=ValidationStatus.SCHEMA_FAILED,
    )


def make_procedural_warning_result() -> ModuleValidationResult:
    """Validation result with only warnings → REVIEW_REQUIRED."""
    return ModuleValidationResult(
        structural_issues=[],
        business_issues=[
            make_procedural_validation_issue(
                code="BIZ-P-002",
                severity=ValidationSeverity.WARNING,
                message="DM title infoName is not set — recommended.",
            ),
        ],
        status=ValidationStatus.REVIEW_REQUIRED,
    )
