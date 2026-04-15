"""Default review gate — decides whether a validated module can be auto-approved.

The review gate is a pure function that examines the validation result and
the module's mapping trace to decide the ``ReviewDecision``.

Decision logic
──────────────
1. If validation has *errors*  → REJECTED, auto_approved=False
2. If validation has *warnings* AND the module contains LLM-derived fields
   with confidence below threshold → NOT_REVIEWED (needs human review)
3. If validation has *warnings* only (no low-confidence LLM fields)
   → APPROVED with advisory, auto_approved=True
4. If validation is clean → APPROVED, auto_approved=True
"""

from __future__ import annotations

from fault_mapper.domain.enums import (
    MappingStrategy,
    ReviewStatus,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.models import S1000DFaultDataModule
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)

# If more than this fraction of fields come from LLM with low confidence,
# the module requires human review even if only warnings exist.
_LLM_LOW_CONFIDENCE_THRESHOLD = 0.5
_MAX_LLM_LOW_CONFIDENCE_RATIO = 0.20


def default_review_gate(
    module: S1000DFaultDataModule,
    validation_result: ModuleValidationResult,
) -> ReviewDecision:
    """Evaluate validation results and decide the review disposition.

    Parameters
    ----------
    module : S1000DFaultDataModule
        The validated module (used for trace inspection).
    validation_result : ModuleValidationResult
        Output of the structural + business validation pass.

    Returns
    -------
    ReviewDecision
        The gating decision, including whether auto-approval is granted.
    """
    reasons: list[str] = []

    # ── Case 1: Errors present → reject ──────────────────────────────
    if validation_result.has_errors:
        error_codes = sorted({
            i.code for i in validation_result.all_issues if i.is_error
        })
        reasons.append(
            f"Validation errors: {', '.join(error_codes)} "
            f"({validation_result.error_count} total)"
        )
        return ReviewDecision(
            review_status=ReviewStatus.REJECTED,
            validation_status=validation_result.status,
            reasons=reasons,
            auto_approved=False,
        )

    # ── Case 2 / 3: Warnings only ────────────────────────────────────
    if validation_result.has_warnings:
        warning_codes = sorted({
            i.code for i in validation_result.all_issues if i.is_warning
        })
        reasons.append(
            f"Validation warnings: {', '.join(warning_codes)} "
            f"({validation_result.warning_count} total)"
        )

        # Check if the module has concerning LLM-derived fields
        if _has_concerning_llm_fields(module):
            reasons.append(
                "Module has LLM-derived fields with low confidence — "
                "human review recommended."
            )
            return ReviewDecision(
                review_status=ReviewStatus.NOT_REVIEWED,
                validation_status=validation_result.status,
                reasons=reasons,
                auto_approved=False,
            )

        # Warnings only, no LLM concerns → auto-approve with advisory
        reasons.append("Warnings are advisory; auto-approved.")
        return ReviewDecision(
            review_status=ReviewStatus.APPROVED,
            validation_status=validation_result.status,
            reasons=reasons,
            auto_approved=True,
        )

    # ── Case 4: Clean validation ──────────────────────────────────────
    reasons.append("All validation checks passed.")
    return ReviewDecision(
        review_status=ReviewStatus.APPROVED,
        validation_status=validation_result.status,
        reasons=reasons,
        auto_approved=True,
    )


# ═══════════════════════════════════════════════════════════════════════
#  PRIVATE HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _has_concerning_llm_fields(module: S1000DFaultDataModule) -> bool:
    """Return True if a non-trivial fraction of LLM fields are low-confidence."""
    trace = module.trace
    if trace is None or not trace.field_origins:
        return False

    llm_fields = [
        origin
        for origin in trace.field_origins.values()
        if origin.strategy is MappingStrategy.LLM
    ]

    if not llm_fields:
        return False

    low_conf = sum(
        1 for o in llm_fields
        if o.confidence < _LLM_LOW_CONFIDENCE_THRESHOLD
    )

    ratio = low_conf / len(llm_fields)
    return ratio > _MAX_LLM_LOW_CONFIDENCE_RATIO
