"""Shared pure helpers for validation services.

Extracted to eliminate duplication between ``FaultModuleValidator``
and ``ProceduralModuleValidator``.
"""

from __future__ import annotations

from fault_mapper.domain.enums import ValidationStatus
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ValidationIssue,
)


def compute_validation_result(
    structural_issues: list[ValidationIssue],
    business_issues: list[ValidationIssue],
) -> ModuleValidationResult:
    """Compute the aggregate validation status from issues."""
    has_structural_errors = any(i.is_error for i in structural_issues)
    has_business_errors = any(i.is_error for i in business_issues)
    has_warnings = any(
        i.is_warning
        for i in (*structural_issues, *business_issues)
    )

    if has_structural_errors:
        status = ValidationStatus.SCHEMA_FAILED
    elif has_business_errors:
        status = ValidationStatus.BUSINESS_RULE_FAILED
    elif has_warnings:
        status = ValidationStatus.REVIEW_REQUIRED
    else:
        status = ValidationStatus.APPROVED

    return ModuleValidationResult(
        structural_issues=structural_issues,
        business_issues=business_issues,
        status=status,
    )
