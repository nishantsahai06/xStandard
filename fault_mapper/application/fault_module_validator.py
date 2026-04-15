"""Fault module validation service — orchestrates post-assembly validation.

This service runs after the assembler produces a ``S1000DFaultDataModule``
and before any persistence or serialisation step.  It composes:

  1. **Structural validation** — canonical model invariants.
  2. **Business-rule validation** — domain-specific deterministic checks.
  3. **Review gating** — decides ``ValidationStatus`` and ``ReviewStatus``
     based on validation results and mapping trace.

The service itself contains NO validation logic — it delegates to
injected validator and review-gate callables.  This keeps it open for
extension (e.g. XSD validation in a future chunk) without modification.

Design notes:
  • Validators are plain callables (duck-typed), not ports.  They are
    deterministic, stateless, and have no external I/O — so the port
    abstraction adds ceremony without value.
  • The review gate IS a callable because its policy may vary by
    deployment, but it remains deterministic and pure.
  • The service mutates the module in-place (validation_status,
    review_status, validation_results) because the module is a mutable
    dataclass and validation is a lifecycle transition, not a new object.
"""

from __future__ import annotations

from typing import Callable

from fault_mapper.domain.enums import (
    ValidationOutcome,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    S1000DFaultDataModule,
    ValidationResults,
)
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)


# Type aliases for injected validators / gate
StructuralValidatorFn = Callable[
    [S1000DFaultDataModule], list[ValidationIssue]
]
BusinessValidatorFn = Callable[
    [S1000DFaultDataModule], list[ValidationIssue]
]
ReviewGateFn = Callable[
    [S1000DFaultDataModule, ModuleValidationResult], ReviewDecision
]


class FaultModuleValidator:
    """Orchestrates validation and review gating for a mapped module.

    Constructor-injected dependencies:
      ``structural_validator`` — returns structural issues.
      ``business_validator``   — returns business-rule issues.
      ``review_gate``          — decides review/validation status.

    All three are plain callables, not ports.
    """

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
        module: S1000DFaultDataModule,
    ) -> ModuleValidationResult:
        """Run all validation checks and apply review gating.

        Steps
        -----
        1. Run structural validation → list of issues.
        2. Run business-rule validation → list of issues.
        3. Compute aggregate ``ModuleValidationResult``.
        4. Run review gate → ``ReviewDecision``.
        5. Mutate module: update ``validation_status``,
           ``review_status``, ``validation_results``.

        Returns
        -------
        ModuleValidationResult
            The full validation result (also reflected on the module).
        """
        # Step 1 + 2: run validators
        structural_issues = self._structural(module)
        business_issues = self._business(module)

        # Step 3: compute aggregate status
        validation_result = _compute_result(
            structural_issues, business_issues,
        )

        # Step 4: review gate
        decision = self._gate(module, validation_result)

        # Step 5: apply to module
        module.validation_status = decision.validation_status
        module.review_status = decision.review_status
        module.validation_results = _build_validation_results(
            validation_result,
        )

        return validation_result


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL HELPERS  (pure)
# ═══════════════════════════════════════════════════════════════════════


def _compute_result(
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


def _build_validation_results(
    result: ModuleValidationResult,
) -> ValidationResults:
    """Map ``ModuleValidationResult`` into the model's ``ValidationResults``."""
    structural_ok = not any(i.is_error for i in result.structural_issues)
    business_ok = not any(i.is_error for i in result.business_issues)

    structural_has_warnings = any(
        i.is_warning for i in result.structural_issues
    )
    business_has_warnings = any(
        i.is_warning for i in result.business_issues
    )

    if not result.structural_issues:
        schema_outcome = ValidationOutcome.NOT_RUN
    elif structural_ok and not structural_has_warnings:
        schema_outcome = ValidationOutcome.PASSED
    elif structural_ok:
        schema_outcome = ValidationOutcome.WARNING
    else:
        schema_outcome = ValidationOutcome.FAILED

    if not result.business_issues:
        biz_outcome = ValidationOutcome.NOT_RUN
    elif business_ok and not business_has_warnings:
        biz_outcome = ValidationOutcome.PASSED
    elif business_ok:
        biz_outcome = ValidationOutcome.WARNING
    else:
        biz_outcome = ValidationOutcome.FAILED

    # Completeness: passed if no issues at all, warning if warnings only
    all_issues = result.all_issues
    if not all_issues:
        completeness = ValidationOutcome.PASSED
    elif result.has_errors:
        completeness = ValidationOutcome.FAILED
    else:
        completeness = ValidationOutcome.WARNING

    return ValidationResults(
        schema=schema_outcome,
        completeness=completeness,
        business_rules=biz_outcome,
    )
