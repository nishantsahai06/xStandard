"""Procedural module validation service — orchestrates post-assembly validation.

Composes:
  1. Structural validation — JSON-schema conformance.
  2. Business-rule validation — deterministic domain checks.
  3. Review gating — decides ValidationStatus and ReviewStatus.

Mutates the module in-place (review_status, validation) as a
lifecycle transition.
"""

from __future__ import annotations

from typing import Callable

from fault_mapper.domain.enums import ValidationStatus
from fault_mapper.domain.procedural_models import (
    ProceduralValidationResults,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)


# Type aliases for injected validators / gate
StructuralValidatorFn = Callable[
    [S1000DProceduralDataModule], list[ValidationIssue]
]
BusinessValidatorFn = Callable[
    [S1000DProceduralDataModule], list[ValidationIssue]
]
ReviewGateFn = Callable[
    [S1000DProceduralDataModule, ModuleValidationResult], ReviewDecision
]


class ProceduralModuleValidator:
    """Orchestrates validation and review gating for a procedural module."""

    def __init__(
        self,
        structural_validator: StructuralValidatorFn,
        business_validator: BusinessValidatorFn,
        review_gate: ReviewGateFn,
    ) -> None:
        self._structural = structural_validator
        self._business = business_validator
        self._gate = review_gate

    def validate(
        self,
        module: S1000DProceduralDataModule,
    ) -> ModuleValidationResult:
        """Run all validation checks and apply review gating.

        Steps:
          1. Run structural validation.
          2. Run business-rule validation.
          3. Compute aggregate ModuleValidationResult.
          4. Run review gate.
          5. Mutate module: update review_status, validation.

        Returns the full validation result.
        """
        structural_issues = self._structural(module)
        business_issues = self._business(module)

        validation_result = _compute_result(
            structural_issues, business_issues,
        )

        decision = self._gate(module, validation_result)

        module.review_status = decision.review_status
        module.validation = _build_procedural_validation_results(
            validation_result, decision,
        )

        return validation_result


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL HELPERS (pure)
# ═══════════════════════════════════════════════════════════════════════


def _compute_result(
    structural_issues: list[ValidationIssue],
    business_issues: list[ValidationIssue],
) -> ModuleValidationResult:
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


def _build_procedural_validation_results(
    result: ModuleValidationResult,
    decision: ReviewDecision,
) -> ProceduralValidationResults:
    """Map ModuleValidationResult into the model's ProceduralValidationResults."""
    schema_valid = not any(i.is_error for i in result.structural_issues)
    business_valid = not any(i.is_error for i in result.business_issues)

    errors = [
        f"[{i.code}] {i.message}"
        for i in result.all_issues
        if i.is_error
    ]
    warnings = [
        f"[{i.code}] {i.message}"
        for i in result.all_issues
        if i.is_warning
    ]

    return ProceduralValidationResults(
        schema_valid=schema_valid,
        business_rule_valid=business_valid,
        status=decision.validation_status,
        errors=errors,
        warnings=warnings,
    )
