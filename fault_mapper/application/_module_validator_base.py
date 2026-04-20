"""Generic template-method base for post-assembly module validators.

Both fault and procedural pipelines run the same 5-step lifecycle:

  1. Run structural validator → list of ``ValidationIssue``.
  2. Run business validator    → list of ``ValidationIssue``.
  3. Compute aggregate ``ModuleValidationResult`` (pure).
  4. Run the review gate       → ``ReviewDecision``.
  5. Apply the decision back to the mutable module dataclass.

Steps 1-4 are identical for every pipeline.  Only step 5 differs —
the fault module writes ``validation_status + review_status +
validation_results``; the procedural module writes ``review_status +
validation``.  Subclasses supply that last step via one hook method.

This base is deliberately a *template-method* pattern rather than a
strategy object because the only variation point is a single mutation
that is tightly coupled to the module's concrete shape.
"""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

from fault_mapper.domain.enums import ValidationStatus
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)

__all__ = ["ModuleValidatorBase", "compute_validation_result"]


TModule = TypeVar("TModule")


def compute_validation_result(
    structural_issues: list[ValidationIssue],
    business_issues: list[ValidationIssue],
) -> ModuleValidationResult:
    """Aggregate structural + business issues into a single result.

    Pure function — shared verbatim across every module-validator
    implementation.  Errors beat warnings; structural beats business.
    """
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


class ModuleValidatorBase(Generic[TModule]):
    """Template-method base for module validators.

    Subclasses override :meth:`_apply_decision` to persist the
    validation + review decision onto the concrete module dataclass.
    Every other step is defined here and not intended to be overridden.
    """

    def __init__(
        self,
        structural_validator: Callable[[TModule], list[ValidationIssue]],
        business_validator: Callable[[TModule], list[ValidationIssue]],
        review_gate: Callable[
            [TModule, ModuleValidationResult], ReviewDecision,
        ],
    ) -> None:
        self._structural = structural_validator
        self._business = business_validator
        self._gate = review_gate

    def validate(self, module: TModule) -> ModuleValidationResult:
        """Run the full 5-step validation lifecycle on *module*."""
        structural_issues = self._structural(module)
        business_issues = self._business(module)

        result = compute_validation_result(
            structural_issues, business_issues,
        )

        decision = self._gate(module, result)
        self._apply_decision(module, result, decision)
        return result

    # ── Hook ─────────────────────────────────────────────────────────
    def _apply_decision(
        self,
        module: TModule,
        result: ModuleValidationResult,
        decision: ReviewDecision,
    ) -> None:
        """Write the validation + review decision onto *module*.

        Subclasses must implement this.  Kept as abstract rather than
        `NotImplementedError` in code to make misuse a type error.
        """
        raise NotImplementedError  # pragma: no cover
