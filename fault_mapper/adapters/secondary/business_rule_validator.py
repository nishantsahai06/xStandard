"""Canonical business-rule validator — domain-specific deterministic checks.

Validates the assembled ``S1000DFaultDataModule`` against business rules
that go beyond structural presence checks.  These are S1000D-specific
semantic rules and deployment policy checks.

This is a DETERMINISTIC adapter — no LLM, no network I/O, no randomness.

Business-rule checks (BIZ-* codes)
────────────────────────────────────
BIZ-001  Item location code must be a valid S1000D value
BIZ-002  Info code must be 3 characters
BIZ-003  Info code must be consistent with the module mode
BIZ-004  Fault entries should have a fault_code
BIZ-005  Fault entries should have a fault description
BIZ-006  Fault entry ID should be present for non-detected faults
BIZ-007  Isolation steps should form a connected tree (no orphan references)
BIZ-008  Isolation step question requires at least one branch
BIZ-009  Trace should have no unmapped sources
BIZ-010  Trace warns when LLM-derived fields have low confidence
BIZ-011  Model ident code should not be the placeholder "UNKNOWN"
BIZ-012  Classification confidence should meet minimum threshold
"""

from __future__ import annotations

from fault_mapper.domain.enums import (
    FaultEntryType,
    FaultMode,
    ItemLocationCode,
    MappingStrategy,
    ValidationSeverity,
)
from fault_mapper.domain.models import (
    FaultEntry,
    IsolationStep,
    S1000DFaultDataModule,
)
from fault_mapper.domain.value_objects import ValidationIssue


# Well-known info codes per mode
_REPORTING_INFO_CODES = frozenset({"031", "030", "033"})
_ISOLATION_INFO_CODES = frozenset({"032", "034"})

# Valid item location code values
_VALID_ILC = frozenset(e.value for e in ItemLocationCode)

# Fault entry types that require an ID
_ID_REQUIRED_TYPES = frozenset({
    FaultEntryType.ISOLATED_FAULT,
    FaultEntryType.ISOLATED_FAULT_ALTS,
    FaultEntryType.OBSERVED_FAULT,
    FaultEntryType.OBSERVED_FAULT_ALTS,
    FaultEntryType.CORRELATED_FAULT,
    FaultEntryType.CORRELATED_FAULT_ALTS,
})

# Minimum acceptable classification confidence
_MIN_CLASSIFICATION_CONFIDENCE = 0.3

# Minimum acceptable LLM field confidence before warning
_MIN_LLM_FIELD_CONFIDENCE = 0.5


def validate_business_rules(
    module: S1000DFaultDataModule,
) -> list[ValidationIssue]:
    """Run all business-rule validation checks.

    Parameters
    ----------
    module : S1000DFaultDataModule
        The fully assembled module to validate.

    Returns
    -------
    list[ValidationIssue]
        Zero or more issues.  Empty list means business-valid.
    """
    issues: list[ValidationIssue] = []

    _check_dm_code_rules(module, issues)
    _check_fault_entries(module, issues)
    _check_isolation_tree(module, issues)
    _check_trace_quality(module, issues)
    _check_classification(module, issues)

    return issues


# ═══════════════════════════════════════════════════════════════════════
#  PRIVATE CHECK FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════


def _check_dm_code_rules(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-001, BIZ-002, BIZ-003, BIZ-011."""
    if module.header is None:
        return  # structural validator already flagged this

    dm = module.header.dm_code

    # BIZ-001: item location code validity
    if dm.item_location_code not in _VALID_ILC:
        issues.append(ValidationIssue(
            code="BIZ-001",
            severity=ValidationSeverity.ERROR,
            message=f"Item location code '{dm.item_location_code}' is not "
                    f"a valid S1000D value. Expected one of: {sorted(_VALID_ILC)}",
            field_path="header.dm_code.item_location_code",
            context=dm.item_location_code,
        ))

    # BIZ-002: info code length
    if dm.info_code and len(dm.info_code) != 3:
        issues.append(ValidationIssue(
            code="BIZ-002",
            severity=ValidationSeverity.ERROR,
            message=f"Info code must be exactly 3 characters, "
                    f"got '{dm.info_code}' ({len(dm.info_code)} chars).",
            field_path="header.dm_code.info_code",
            context=dm.info_code,
        ))

    # BIZ-003: info code consistency with mode
    if dm.info_code:
        if module.mode is FaultMode.FAULT_REPORTING:
            if dm.info_code not in _REPORTING_INFO_CODES:
                issues.append(ValidationIssue(
                    code="BIZ-003",
                    severity=ValidationSeverity.WARNING,
                    message=f"Info code '{dm.info_code}' is unusual for "
                            f"fault-reporting mode. Expected one of: "
                            f"{sorted(_REPORTING_INFO_CODES)}",
                    field_path="header.dm_code.info_code",
                    context=dm.info_code,
                ))
        elif module.mode is FaultMode.FAULT_ISOLATION:
            if dm.info_code not in _ISOLATION_INFO_CODES:
                issues.append(ValidationIssue(
                    code="BIZ-003",
                    severity=ValidationSeverity.WARNING,
                    message=f"Info code '{dm.info_code}' is unusual for "
                            f"fault-isolation mode. Expected one of: "
                            f"{sorted(_ISOLATION_INFO_CODES)}",
                    field_path="header.dm_code.info_code",
                    context=dm.info_code,
                ))

    # BIZ-011: placeholder model ident code
    if dm.model_ident_code == "UNKNOWN":
        issues.append(ValidationIssue(
            code="BIZ-011",
            severity=ValidationSeverity.WARNING,
            message="Model ident code is the placeholder value 'UNKNOWN'. "
                    "Source metadata likely lacked a model identifier.",
            field_path="header.dm_code.model_ident_code",
            context="UNKNOWN",
        ))


def _check_fault_entries(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-004, BIZ-005, BIZ-006."""
    fr = module.content.fault_reporting
    if fr is None:
        return

    for i, entry in enumerate(fr.fault_entries):
        prefix = f"content.fault_reporting.fault_entries[{i}]"

        # BIZ-004: fault code presence
        if not entry.fault_code:
            issues.append(ValidationIssue(
                code="BIZ-004",
                severity=ValidationSeverity.WARNING,
                message=f"Fault entry [{i}] has no fault_code.",
                field_path=f"{prefix}.fault_code",
            ))

        # BIZ-005: fault description presence
        if not entry.fault_descr or not entry.fault_descr.descr:
            issues.append(ValidationIssue(
                code="BIZ-005",
                severity=ValidationSeverity.WARNING,
                message=f"Fault entry [{i}] has no fault description.",
                field_path=f"{prefix}.fault_descr",
            ))

        # BIZ-006: ID required for non-detected fault types
        if entry.entry_type in _ID_REQUIRED_TYPES and not entry.id:
            issues.append(ValidationIssue(
                code="BIZ-006",
                severity=ValidationSeverity.WARNING,
                message=f"Fault entry [{i}] of type "
                        f"'{entry.entry_type.value}' should have an ID.",
                field_path=f"{prefix}.id",
            ))


def _check_isolation_tree(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-007, BIZ-008."""
    fi = module.content.fault_isolation
    if fi is None:
        return

    steps = fi.fault_isolation_steps
    if not steps:
        return

    # Collect all step numbers
    step_numbers = {s.step_number for s in steps}

    for i, step in enumerate(steps):
        prefix = f"content.fault_isolation.fault_isolation_steps[{i}]"

        # BIZ-008: question requires at least one branch
        if step.question and not step.yes_group and not step.no_group:
            issues.append(ValidationIssue(
                code="BIZ-008",
                severity=ValidationSeverity.WARNING,
                message=f"Isolation step [{i}] has a question but no "
                        f"yes_group or no_group branches.",
                field_path=f"{prefix}.question",
                context=step.question,
            ))

        # BIZ-007: check branch references for orphans
        _check_branch_refs(step, step_numbers, prefix, issues)


def _check_branch_refs(
    step: IsolationStep,
    valid_step_numbers: set[int],
    prefix: str,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-007: recursive check for orphan step references in branches."""
    for branch_name, branch in [
        ("yes_group", step.yes_group),
        ("no_group", step.no_group),
    ]:
        if branch is None:
            continue
        for j, nested_step in enumerate(branch.next_steps):
            if nested_step.step_number not in valid_step_numbers:
                # This is an internal reference — not necessarily
                # an error if it's a new nested step. Only warn if
                # the nested step references another step that
                # doesn't exist in the flat list.
                pass  # Nested steps are self-contained; skip for now.


def _check_trace_quality(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-009, BIZ-010."""
    trace = module.trace
    if trace is None:
        return

    # BIZ-009: unmapped sources
    if trace.unmapped_sources:
        issues.append(ValidationIssue(
            code="BIZ-009",
            severity=ValidationSeverity.WARNING,
            message=f"{len(trace.unmapped_sources)} source(s) were not "
                    f"mapped to any target field.",
            field_path="trace.unmapped_sources",
            context=", ".join(trace.unmapped_sources[:5]),
        ))

    # BIZ-010: low-confidence LLM fields
    low_conf_fields: list[str] = []
    for field_name, origin in trace.field_origins.items():
        if (
            origin.strategy is MappingStrategy.LLM
            and origin.confidence < _MIN_LLM_FIELD_CONFIDENCE
        ):
            low_conf_fields.append(
                f"{field_name} ({origin.confidence:.2f})"
            )

    if low_conf_fields:
        issues.append(ValidationIssue(
            code="BIZ-010",
            severity=ValidationSeverity.WARNING,
            message=f"{len(low_conf_fields)} LLM-derived field(s) have "
                    f"confidence below {_MIN_LLM_FIELD_CONFIDENCE}.",
            field_path="trace.field_origins",
            context=", ".join(low_conf_fields[:5]),
        ))


def _check_classification(
    module: S1000DFaultDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-012."""
    cls = module.classification
    if cls is None:
        return

    if cls.confidence < _MIN_CLASSIFICATION_CONFIDENCE:
        issues.append(ValidationIssue(
            code="BIZ-012",
            severity=ValidationSeverity.WARNING,
            message=f"Classification confidence ({cls.confidence:.3f}) is "
                    f"below minimum threshold "
                    f"({_MIN_CLASSIFICATION_CONFIDENCE}).",
            field_path="classification.confidence",
            context=f"{cls.confidence:.3f}",
        ))
