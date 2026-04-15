"""Canonical structural validator — checks S1000DFaultDataModule invariants.

Validates the assembled module against the internal canonical model rules.
These are structural/schema-level checks that are independent of
business-specific deployment rules.

This is a DETERMINISTIC adapter — no LLM, no network I/O, no randomness.
It reads the module's fields and returns a list of ``ValidationIssue``s.

Structural checks (STRUCT-* codes)
───────────────────────────────────
STRUCT-001  Header must be present
STRUCT-002  DM code must have all required segments non-empty
STRUCT-003  Exactly one of faultReporting / faultIsolation must be set
STRUCT-004  Module mode must match the populated content block
STRUCT-005  Record ID must be present and non-empty
STRUCT-006  Mapping version must be present
STRUCT-007  Trace must be present
STRUCT-008  Provenance must be present
STRUCT-009  DM title tech_name must be present
STRUCT-010  Language fields must be non-empty
STRUCT-011  Issue info must have valid format
STRUCT-012  Issue date must have valid format
STRUCT-013  Fault reporting must have at least one fault entry
STRUCT-014  Fault isolation must have at least one isolation step
STRUCT-015  Each fault entry must have an entry_type
STRUCT-016  Each isolation step must have a positive step_number
STRUCT-017  Each isolation step must have non-empty instruction
"""

from __future__ import annotations

import re

from fault_mapper.domain.enums import FaultMode, ValidationSeverity
from fault_mapper.domain.models import (
    FaultEntry,
    IsolationStep,
    S1000DFaultDataModule,
)
from fault_mapper.domain.value_objects import ValidationIssue


# ── regex for format checks ──────────────────────────────────────────
_ISSUE_NUMBER_RE = re.compile(r"^\d{3}$")
_IN_WORK_RE = re.compile(r"^\d{2}$")
_YEAR_RE = re.compile(r"^\d{4}$")
_MONTH_RE = re.compile(r"^(0[1-9]|1[0-2])$")
_DAY_RE = re.compile(r"^(0[1-9]|[12]\d|3[01])$")


def validate_structure(
    module: S1000DFaultDataModule,
) -> list[ValidationIssue]:
    """Run all canonical structural validation checks.

    Parameters
    ----------
    module : S1000DFaultDataModule
        The fully assembled module to validate.

    Returns
    -------
    list[ValidationIssue]
        Zero or more issues.  Empty list means structurally valid.
    """
    issues: list[ValidationIssue] = []

    _check_identity(module, issues)
    _check_header(module, issues)
    _check_content_mode(module, issues)
    _check_traceability(module, issues)
    _check_fault_reporting(module, issues)
    _check_fault_isolation(module, issues)

    return issues


# ═══════════════════════════════════════════════════════════════════════
#  PRIVATE CHECK FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════


def _check_identity(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """STRUCT-005, STRUCT-006."""
    if not module.record_id:
        issues.append(ValidationIssue(
            code="STRUCT-005",
            severity=ValidationSeverity.ERROR,
            message="Record ID is missing or empty.",
            field_path="record_id",
        ))
    if not module.mapping_version:
        issues.append(ValidationIssue(
            code="STRUCT-006",
            severity=ValidationSeverity.ERROR,
            message="Mapping version is missing.",
            field_path="mapping_version",
        ))


def _check_header(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """STRUCT-001, STRUCT-002, STRUCT-009, STRUCT-010, STRUCT-011, STRUCT-012."""
    if module.header is None:
        issues.append(ValidationIssue(
            code="STRUCT-001",
            severity=ValidationSeverity.ERROR,
            message="Header is missing.",
            field_path="header",
        ))
        return  # no point checking sub-fields

    hdr = module.header

    # STRUCT-002: DM code segments
    dm = hdr.dm_code
    required_segments = [
        ("model_ident_code", dm.model_ident_code),
        ("system_diff_code", dm.system_diff_code),
        ("system_code", dm.system_code),
        ("sub_system_code", dm.sub_system_code),
        ("sub_sub_system_code", dm.sub_sub_system_code),
        ("assy_code", dm.assy_code),
        ("disassy_code", dm.disassy_code),
        ("disassy_code_variant", dm.disassy_code_variant),
        ("info_code", dm.info_code),
        ("info_code_variant", dm.info_code_variant),
        ("item_location_code", dm.item_location_code),
    ]
    for seg_name, seg_value in required_segments:
        if not seg_value:
            issues.append(ValidationIssue(
                code="STRUCT-002",
                severity=ValidationSeverity.ERROR,
                message=f"DM code segment '{seg_name}' is missing or empty.",
                field_path=f"header.dm_code.{seg_name}",
            ))

    # STRUCT-009: title
    if not hdr.dm_title or not hdr.dm_title.tech_name:
        issues.append(ValidationIssue(
            code="STRUCT-009",
            severity=ValidationSeverity.ERROR,
            message="DM title tech_name is missing.",
            field_path="header.dm_title.tech_name",
        ))

    # STRUCT-010: language
    lang = hdr.language
    if not lang.language_iso_code:
        issues.append(ValidationIssue(
            code="STRUCT-010",
            severity=ValidationSeverity.ERROR,
            message="Language ISO code is missing.",
            field_path="header.language.language_iso_code",
        ))
    if not lang.country_iso_code:
        issues.append(ValidationIssue(
            code="STRUCT-010",
            severity=ValidationSeverity.ERROR,
            message="Country ISO code is missing.",
            field_path="header.language.country_iso_code",
        ))

    # STRUCT-011: issue info format
    ii = hdr.issue_info
    if not _ISSUE_NUMBER_RE.match(ii.issue_number or ""):
        issues.append(ValidationIssue(
            code="STRUCT-011",
            severity=ValidationSeverity.ERROR,
            message="Issue number must be exactly 3 digits.",
            field_path="header.issue_info.issue_number",
            context=ii.issue_number,
        ))
    if not _IN_WORK_RE.match(ii.in_work or ""):
        issues.append(ValidationIssue(
            code="STRUCT-011",
            severity=ValidationSeverity.ERROR,
            message="In-work indicator must be exactly 2 digits.",
            field_path="header.issue_info.in_work",
            context=ii.in_work,
        ))

    # STRUCT-012: issue date format
    dt = hdr.issue_date
    if not _YEAR_RE.match(dt.year or ""):
        issues.append(ValidationIssue(
            code="STRUCT-012",
            severity=ValidationSeverity.ERROR,
            message="Issue date year must be exactly 4 digits.",
            field_path="header.issue_date.year",
            context=dt.year,
        ))
    if not _MONTH_RE.match(dt.month or ""):
        issues.append(ValidationIssue(
            code="STRUCT-012",
            severity=ValidationSeverity.ERROR,
            message="Issue date month must be 01-12.",
            field_path="header.issue_date.month",
            context=dt.month,
        ))
    if not _DAY_RE.match(dt.day or ""):
        issues.append(ValidationIssue(
            code="STRUCT-012",
            severity=ValidationSeverity.ERROR,
            message="Issue date day must be 01-31.",
            field_path="header.issue_date.day",
            context=dt.day,
        ))


def _check_content_mode(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """STRUCT-003, STRUCT-004."""
    content = module.content
    has_reporting = content.fault_reporting is not None
    has_isolation = content.fault_isolation is not None

    if has_reporting and has_isolation:
        issues.append(ValidationIssue(
            code="STRUCT-003",
            severity=ValidationSeverity.ERROR,
            message="Both faultReporting and faultIsolation are populated. "
                    "Exactly one must be set.",
            field_path="content",
        ))
    elif not has_reporting and not has_isolation:
        issues.append(ValidationIssue(
            code="STRUCT-003",
            severity=ValidationSeverity.ERROR,
            message="Neither faultReporting nor faultIsolation is populated. "
                    "Exactly one must be set.",
            field_path="content",
        ))

    # STRUCT-004: mode must match the populated block
    if has_reporting and module.mode is not FaultMode.FAULT_REPORTING:
        issues.append(ValidationIssue(
            code="STRUCT-004",
            severity=ValidationSeverity.ERROR,
            message="Module mode is FAULT_ISOLATION but faultReporting "
                    "content is populated.",
            field_path="mode",
            context=module.mode.value,
        ))
    if has_isolation and module.mode is not FaultMode.FAULT_ISOLATION:
        issues.append(ValidationIssue(
            code="STRUCT-004",
            severity=ValidationSeverity.ERROR,
            message="Module mode is FAULT_REPORTING but faultIsolation "
                    "content is populated.",
            field_path="mode",
            context=module.mode.value,
        ))


def _check_traceability(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """STRUCT-007, STRUCT-008."""
    if module.trace is None:
        issues.append(ValidationIssue(
            code="STRUCT-007",
            severity=ValidationSeverity.ERROR,
            message="Mapping trace is missing.",
            field_path="trace",
        ))

    if module.provenance is None:
        issues.append(ValidationIssue(
            code="STRUCT-008",
            severity=ValidationSeverity.WARNING,
            message="Provenance is missing.",
            field_path="provenance",
        ))


def _check_fault_reporting(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """STRUCT-013, STRUCT-015."""
    fr = module.content.fault_reporting
    if fr is None:
        return

    if not fr.fault_entries:
        issues.append(ValidationIssue(
            code="STRUCT-013",
            severity=ValidationSeverity.ERROR,
            message="Fault reporting content has no fault entries.",
            field_path="content.fault_reporting.fault_entries",
        ))
        return

    for i, entry in enumerate(fr.fault_entries):
        _check_fault_entry(entry, i, issues)


def _check_fault_entry(
    entry: FaultEntry,
    index: int,
    issues: list[ValidationIssue],
) -> None:
    """STRUCT-015: each entry must have an entry_type."""
    if not entry.entry_type:
        issues.append(ValidationIssue(
            code="STRUCT-015",
            severity=ValidationSeverity.ERROR,
            message=f"Fault entry [{index}] is missing entry_type.",
            field_path=f"content.fault_reporting.fault_entries[{index}].entry_type",
        ))


def _check_fault_isolation(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """STRUCT-014, STRUCT-016, STRUCT-017."""
    fi = module.content.fault_isolation
    if fi is None:
        return

    if not fi.fault_isolation_steps:
        issues.append(ValidationIssue(
            code="STRUCT-014",
            severity=ValidationSeverity.ERROR,
            message="Fault isolation content has no isolation steps.",
            field_path="content.fault_isolation.fault_isolation_steps",
        ))
        return

    for i, step in enumerate(fi.fault_isolation_steps):
        _check_isolation_step(step, i, issues)


def _check_isolation_step(
    step: IsolationStep,
    index: int,
    issues: list[ValidationIssue],
) -> None:
    """STRUCT-016, STRUCT-017."""
    if step.step_number < 1:
        issues.append(ValidationIssue(
            code="STRUCT-016",
            severity=ValidationSeverity.ERROR,
            message=f"Isolation step [{index}] has non-positive step_number "
                    f"({step.step_number}).",
            field_path=f"content.fault_isolation.fault_isolation_steps[{index}].step_number",
            context=str(step.step_number),
        ))
    if not step.instruction:
        issues.append(ValidationIssue(
            code="STRUCT-017",
            severity=ValidationSeverity.ERROR,
            message=f"Isolation step [{index}] has empty instruction.",
            field_path=f"content.fault_isolation.fault_isolation_steps[{index}].instruction",
        ))
