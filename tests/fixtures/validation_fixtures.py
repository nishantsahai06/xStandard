"""Validation-layer fixture builders — schema-valid defaults.

These builders produce ``S1000DFaultDataModule`` instances whose DM code
segments, provenance, and content shapes pass the canonical JSON Schema
out of the box.  They are intentionally SEPARATE from the conftest
factories so existing 95 tests are never affected.

Corrections vs conftest ``make_dm_code`` defaults
──────────────────────────────────────────────────
  • sub_system_code   : "00" → "0"   (schema: ^[A-Z0-9]{1}$)
  • sub_sub_system_code: "00" → "0"  (schema: ^[A-Z0-9]{1}$)
  • disassy_code       : "A"  → "AA" (schema: ^[A-Z0-9]{2}$)
"""

from __future__ import annotations

from typing import Any

from fault_mapper.domain.enums import (
    ClassificationMethod,
    FaultEntryType,
    FaultMode,
    MappingStrategy,
    ReviewStatus,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    Classification,
    FaultContent,
    FaultDescription,
    FaultEntry,
    FaultHeader,
    FaultIsolationContent,
    FaultReportingContent,
    IsolationStep,
    IsolationStepBranch,
    Provenance,
    S1000DFaultDataModule,
    ValidationResults,
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


def make_valid_dm_code(**overrides: Any) -> DmCode:
    """DM code whose every segment satisfies the JSON Schema patterns."""
    defaults = dict(
        model_ident_code="TESTAC",
        system_diff_code="A",
        system_code="29",
        sub_system_code="0",           # 1 char
        sub_sub_system_code="0",       # 1 char
        assy_code="00",                # 2 chars
        disassy_code="AA",             # 2 chars
        disassy_code_variant="A",
        info_code="031",
        info_code_variant="A",
        item_location_code="A",
    )
    defaults.update(overrides)
    return DmCode(**defaults)


def make_valid_header(**overrides: Any) -> FaultHeader:
    """Fully schema-valid header."""
    defaults = dict(
        dm_code=make_valid_dm_code(),
        language=Language(language_iso_code="en", country_iso_code="US"),
        issue_info=IssueInfo(issue_number="001", in_work="00"),
        issue_date=IssueDate(year="2026", month="04", day="13"),
        dm_title=DmTitle(tech_name="Fault Report", info_name="Fault Reporting"),
    )
    defaults.update(overrides)
    return FaultHeader(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  WHOLE-MODULE BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_valid_fault_reporting_module(**overrides: Any) -> S1000DFaultDataModule:
    """Minimal module that passes BOTH schema and business-rule validation.

    Mode: faultReporting, info_code="031", one valid fault entry.
    """
    defaults = dict(
        record_id="REC-001",
        mode=FaultMode.FAULT_REPORTING,
        header=make_valid_header(),
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            fault_reporting=FaultReportingContent(
                fault_entries=[
                    FaultEntry(
                        entry_type=FaultEntryType.DETECTED_FAULT,
                        fault_code="FC001",
                        fault_descr=FaultDescription(descr="Detected fault."),
                    ),
                ],
            ),
        ),
        provenance=Provenance(
            source_document_id="doc-001",
            source_section_ids=["sec-1"],
        ),
    )
    defaults.update(overrides)
    return S1000DFaultDataModule(**defaults)


def make_valid_fault_isolation_module(**overrides: Any) -> S1000DFaultDataModule:
    """Minimal module that passes schema + business-rule validation.

    Mode: faultIsolation, info_code="032", one valid isolation step.
    """
    defaults = dict(
        record_id="REC-002",
        mode=FaultMode.FAULT_ISOLATION,
        header=make_valid_header(
            dm_code=make_valid_dm_code(info_code="032"),
        ),
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            fault_isolation=FaultIsolationContent(
                fault_isolation_steps=[
                    IsolationStep(
                        step_number=1,
                        instruction="Check power supply.",
                    ),
                ],
            ),
        ),
        provenance=Provenance(
            source_document_id="doc-002",
            source_section_ids=["sec-2"],
        ),
    )
    defaults.update(overrides)
    return S1000DFaultDataModule(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  INVALID / EDGE-CASE BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_module_missing_header() -> S1000DFaultDataModule:
    """Module with ``header=None`` — triggers SCHEMA required-property error."""
    return S1000DFaultDataModule(
        record_id="REC-BAD-001",
        mode=FaultMode.FAULT_REPORTING,
        header=None,
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            fault_reporting=FaultReportingContent(
                fault_entries=[
                    FaultEntry(
                        entry_type=FaultEntryType.DETECTED_FAULT,
                        fault_code="FC001",
                        fault_descr=FaultDescription(descr="Test"),
                    ),
                ],
            ),
        ),
        provenance=Provenance(
            source_document_id="doc-001",
            source_section_ids=["sec-1"],
        ),
    )


def make_module_bad_patterns() -> S1000DFaultDataModule:
    """Module with DM code segments that violate schema regex patterns."""
    return make_valid_fault_reporting_module(
        record_id="REC-BAD-002",
        header=make_valid_header(
            dm_code=make_valid_dm_code(
                sub_system_code="00",          # 2 chars, needs 1
                sub_sub_system_code="zz",      # lowercase, needs upper
                disassy_code="A",              # 1 char, needs 2
            ),
        ),
    )


def make_module_mode_content_mismatch() -> S1000DFaultDataModule:
    """Mode is faultIsolation but content only has faultReporting."""
    return S1000DFaultDataModule(
        record_id="REC-BAD-003",
        mode=FaultMode.FAULT_ISOLATION,
        header=make_valid_header(
            dm_code=make_valid_dm_code(info_code="032"),
        ),
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            # faultIsolation is missing — schema allOf/if-then will fail
            fault_reporting=FaultReportingContent(
                fault_entries=[
                    FaultEntry(
                        entry_type=FaultEntryType.DETECTED_FAULT,
                        fault_code="FC001",
                        fault_descr=FaultDescription(descr="Test"),
                    ),
                ],
            ),
        ),
        provenance=Provenance(
            source_document_id="doc-001",
            source_section_ids=["sec-1"],
        ),
    )


def make_module_missing_provenance() -> S1000DFaultDataModule:
    """Module with ``provenance=None`` — missing sourceDocumentId."""
    return S1000DFaultDataModule(
        record_id="REC-BAD-004",
        mode=FaultMode.FAULT_REPORTING,
        header=make_valid_header(),
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            fault_reporting=FaultReportingContent(
                fault_entries=[
                    FaultEntry(
                        entry_type=FaultEntryType.DETECTED_FAULT,
                        fault_code="FC001",
                        fault_descr=FaultDescription(descr="Test"),
                    ),
                ],
            ),
        ),
        provenance=None,
    )


# ═══════════════════════════════════════════════════════════════════════
#  BUSINESS-RULE SPECIFIC BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_module_biz_invalid_ilc() -> S1000DFaultDataModule:
    """BIZ-001: invalid item_location_code."""
    return make_valid_fault_reporting_module(
        record_id="REC-BIZ-001",
        header=make_valid_header(
            dm_code=make_valid_dm_code(item_location_code="Z"),
        ),
    )


def make_module_biz_bad_info_code_length() -> S1000DFaultDataModule:
    """BIZ-002: info_code with wrong length (but passes schema pattern ^[A-Z0-9]{3}$)."""
    # 2-char info_code — will also fail schema pattern, but BIZ-002 checks length
    return make_valid_fault_reporting_module(
        record_id="REC-BIZ-002",
        header=make_valid_header(
            dm_code=make_valid_dm_code(info_code="03"),
        ),
    )


def make_module_biz_info_code_mismatch() -> S1000DFaultDataModule:
    """BIZ-003: reporting mode with isolation info code."""
    return make_valid_fault_reporting_module(
        record_id="REC-BIZ-003",
        header=make_valid_header(
            dm_code=make_valid_dm_code(info_code="032"),  # isolation code
        ),
    )


def make_module_biz_missing_fault_code() -> S1000DFaultDataModule:
    """BIZ-004: fault entry with no fault_code."""
    return make_valid_fault_reporting_module(
        record_id="REC-BIZ-004",
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            fault_reporting=FaultReportingContent(
                fault_entries=[
                    FaultEntry(
                        entry_type=FaultEntryType.DETECTED_FAULT,
                        fault_code=None,
                        fault_descr=FaultDescription(descr="No fault code"),
                    ),
                ],
            ),
        ),
    )


def make_module_biz_missing_fault_descr() -> S1000DFaultDataModule:
    """BIZ-005: fault entry with no fault_descr."""
    return make_valid_fault_reporting_module(
        record_id="REC-BIZ-005",
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            fault_reporting=FaultReportingContent(
                fault_entries=[
                    FaultEntry(
                        entry_type=FaultEntryType.DETECTED_FAULT,
                        fault_code="FC001",
                        fault_descr=None,
                    ),
                ],
            ),
        ),
    )


def make_module_biz_missing_id_for_isolated() -> S1000DFaultDataModule:
    """BIZ-006: isolatedFault entry missing ID."""
    return make_valid_fault_reporting_module(
        record_id="REC-BIZ-006",
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            fault_reporting=FaultReportingContent(
                fault_entries=[
                    FaultEntry(
                        entry_type=FaultEntryType.ISOLATED_FAULT,
                        id=None,  # required for non-detected types
                        fault_code="FC001",
                        fault_descr=FaultDescription(descr="Isolated."),
                    ),
                ],
            ),
        ),
    )


def make_module_biz_question_without_branches() -> S1000DFaultDataModule:
    """BIZ-008: isolation step has question but no yes/no branches."""
    return make_valid_fault_isolation_module(
        record_id="REC-BIZ-008",
        content=FaultContent(
            refs=[],
            warnings_and_cautions=[],
            fault_isolation=FaultIsolationContent(
                fault_isolation_steps=[
                    IsolationStep(
                        step_number=1,
                        instruction="Check power.",
                        question="Is power light on?",
                        yes_group=None,
                        no_group=None,
                    ),
                ],
            ),
        ),
    )


def make_module_biz_unknown_model_ident() -> S1000DFaultDataModule:
    """BIZ-011: model_ident_code = 'UNKNOWN'."""
    return make_valid_fault_reporting_module(
        record_id="REC-BIZ-011",
        header=make_valid_header(
            dm_code=make_valid_dm_code(model_ident_code="UNKNOWN"),
        ),
    )


def make_module_biz_low_classification_confidence() -> S1000DFaultDataModule:
    """BIZ-012: classification confidence below 0.3."""
    return make_valid_fault_reporting_module(
        record_id="REC-BIZ-012",
        classification=Classification(
            domain="S1000D",
            confidence=0.15,
            method=ClassificationMethod.LLM,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
#  TRACE / LLM-CONFIDENCE BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_trace_high_confidence() -> MappingTrace:
    """All fields mapped with high confidence (≥ 0.9)."""
    return MappingTrace(
        field_origins={
            "header.dm_code": FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path="section.title",
                confidence=0.95,
            ),
            "content.fault_entries": FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="section.chunks[0]",
                confidence=0.92,
            ),
        },
        warnings=[],
    )


def make_trace_low_confidence_llm() -> MappingTrace:
    """Majority of LLM fields below 0.5 confidence → triggers BIZ-010 + gate."""
    return MappingTrace(
        field_origins={
            "header.dm_code": FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path="section.title",
                confidence=0.95,
            ),
            "content.fault_entries[0].fault_code": FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="section.chunks[0]",
                confidence=0.3,
            ),
            "content.fault_entries[0].fault_descr": FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="section.chunks[1]",
                confidence=0.25,
            ),
            "content.fault_entries[0].detection_info": FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="section.chunks[2]",
                confidence=0.4,
            ),
        },
        warnings=["Low LLM confidence on multiple fields"],
    )


def make_trace_with_unmapped_sources() -> MappingTrace:
    """Trace with unmapped sources → triggers BIZ-009."""
    return MappingTrace(
        field_origins={
            "header.dm_code": FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path="section.title",
                confidence=0.95,
            ),
        },
        warnings=[],
        unmapped_sources=["chunk-99", "table-42"],
    )


def make_module_with_low_confidence_trace() -> S1000DFaultDataModule:
    """Module with low-confidence LLM trace — BIZ-010 + review-gate concern."""
    return make_valid_fault_reporting_module(
        record_id="REC-LOW-CONF",
        trace=make_trace_low_confidence_llm(),
    )


def make_module_with_unmapped_sources() -> S1000DFaultDataModule:
    """Module with unmapped sources — BIZ-009."""
    return make_valid_fault_reporting_module(
        record_id="REC-UNMAPPED",
        trace=make_trace_with_unmapped_sources(),
    )


# ═══════════════════════════════════════════════════════════════════════
#  VALIDATION RESULT BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_validation_issue(
    code: str = "TEST-001",
    severity: ValidationSeverity = ValidationSeverity.WARNING,
    message: str = "Test issue.",
    field_path: str | None = None,
    context: str | None = None,
) -> ValidationIssue:
    """Convenience builder for a single ValidationIssue."""
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        field_path=field_path,
        context=context,
    )


def make_clean_validation_result() -> ModuleValidationResult:
    """Validation result with zero issues → APPROVED."""
    return ModuleValidationResult(
        structural_issues=[],
        business_issues=[],
        status=ValidationStatus.APPROVED,
    )


def make_error_validation_result() -> ModuleValidationResult:
    """Validation result with structural errors → SCHEMA_FAILED."""
    return ModuleValidationResult(
        structural_issues=[
            make_validation_issue(
                code="SCHEMA-001",
                severity=ValidationSeverity.ERROR,
                message="Missing required property: 'header'",
            ),
        ],
        business_issues=[],
        status=ValidationStatus.SCHEMA_FAILED,
    )


def make_warning_validation_result() -> ModuleValidationResult:
    """Validation result with only warnings → REVIEW_REQUIRED."""
    return ModuleValidationResult(
        structural_issues=[],
        business_issues=[
            make_validation_issue(
                code="BIZ-004",
                severity=ValidationSeverity.WARNING,
                message="Fault entry [0] has no fault_code.",
            ),
        ],
        status=ValidationStatus.REVIEW_REQUIRED,
    )


def make_biz_error_validation_result() -> ModuleValidationResult:
    """Validation result with business-rule errors → BUSINESS_RULE_FAILED."""
    return ModuleValidationResult(
        structural_issues=[],
        business_issues=[
            make_validation_issue(
                code="BIZ-001",
                severity=ValidationSeverity.ERROR,
                message="Invalid item location code.",
            ),
        ],
        status=ValidationStatus.BUSINESS_RULE_FAILED,
    )
