"""Fault module validation service — post-assembly orchestration.

This service runs after the assembler produces a
``S1000DFaultDataModule`` and before any persistence or serialisation
step.  The 5-step lifecycle (structural → business → aggregate →
gate → apply) lives in :class:`ModuleValidatorBase`.  This module
only contributes the *apply-decision* hook and the fault-specific
mapping from ``ModuleValidationResult`` to
``ValidationResults``.

Design notes
────────────
• Validators are plain callables (duck-typed), not ports.  They are
  deterministic, stateless, and have no external I/O — so a port
  abstraction adds ceremony without value.
• The service mutates the module in-place because the module is a
  mutable dataclass and validation is a lifecycle transition, not a
  new object.
"""

from __future__ import annotations

from fault_mapper.application._module_validator_base import (
    ModuleValidatorBase,
    compute_validation_result,  # re-exported for backward compat
)
from fault_mapper.domain.enums import ValidationOutcome
from fault_mapper.domain.models import (
    S1000DFaultDataModule,
    ValidationResults,
)
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)


# Type aliases retained for backward-compat with existing imports.
StructuralValidatorFn = (
    "Callable[[S1000DFaultDataModule], list[ValidationIssue]]"
)
BusinessValidatorFn = (
    "Callable[[S1000DFaultDataModule], list[ValidationIssue]]"
)
ReviewGateFn = (
    "Callable[[S1000DFaultDataModule, ModuleValidationResult], "
    "ReviewDecision]"
)


class FaultModuleValidator(ModuleValidatorBase[S1000DFaultDataModule]):
    """Fault-specific module validator.

    Inherits the 5-step validation lifecycle from
    :class:`ModuleValidatorBase` and contributes only the
    fault-specific write-back step:

      * ``validation_status`` ← ``decision.validation_status``
      * ``review_status``     ← ``decision.review_status``
      * ``validation_results`` ← derived from issues + decision
    """

    def _apply_decision(
        self,
        module: S1000DFaultDataModule,
        result: ModuleValidationResult,
        decision: ReviewDecision,
    ) -> None:
        module.validation_status = decision.validation_status
        module.review_status = decision.review_status
        module.validation_results = _build_validation_results(result)


# ═══════════════════════════════════════════════════════════════════════
#  Backward-compat alias — existing tests import _compute_result.
# ═══════════════════════════════════════════════════════════════════════

_compute_result = compute_validation_result


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL HELPERS  (pure, fault-specific)
# ═══════════════════════════════════════════════════════════════════════


def _build_validation_results(
    result: ModuleValidationResult,
) -> ValidationResults:
    """Map ``ModuleValidationResult`` into the fault model's ``ValidationResults``."""
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
