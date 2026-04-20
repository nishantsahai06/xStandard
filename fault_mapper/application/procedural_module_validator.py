"""Procedural module validation service — post-assembly orchestration.

The 5-step lifecycle (structural → business → aggregate → gate →
apply) lives in :class:`ModuleValidatorBase`.  This module only
contributes the *apply-decision* hook for procedural modules and the
procedural-specific mapping from ``ModuleValidationResult`` to
``ProceduralValidationResults``.
"""

from __future__ import annotations

from fault_mapper.application._module_validator_base import (
    ModuleValidatorBase,
    compute_validation_result,  # re-exported for backward compat
)
from fault_mapper.domain.procedural_models import (
    ProceduralValidationResults,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)


# Type aliases retained for backward-compat with existing imports.
StructuralValidatorFn = (
    "Callable[[S1000DProceduralDataModule], list[ValidationIssue]]"
)
BusinessValidatorFn = (
    "Callable[[S1000DProceduralDataModule], list[ValidationIssue]]"
)
ReviewGateFn = (
    "Callable[[S1000DProceduralDataModule, ModuleValidationResult], "
    "ReviewDecision]"
)


class ProceduralModuleValidator(
    ModuleValidatorBase[S1000DProceduralDataModule],
):
    """Procedural-specific module validator.

    Inherits the 5-step validation lifecycle from
    :class:`ModuleValidatorBase` and contributes only the
    procedural-specific write-back step:

      * ``review_status`` ← ``decision.review_status``
      * ``validation``    ← derived from issues + decision
    """

    def _apply_decision(
        self,
        module: S1000DProceduralDataModule,
        result: ModuleValidationResult,
        decision: ReviewDecision,
    ) -> None:
        module.review_status = decision.review_status
        module.validation = _build_procedural_validation_results(
            result, decision,
        )


# Backward-compat alias — some tests import _compute_result.
_compute_result = compute_validation_result


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL HELPERS (pure, procedural-specific)
# ═══════════════════════════════════════════════════════════════════════


def _build_procedural_validation_results(
    result: ModuleValidationResult,
    decision: ReviewDecision,
) -> ProceduralValidationResults:
    """Map ``ModuleValidationResult`` into the procedural model's
    ``ProceduralValidationResults``.
    """
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
