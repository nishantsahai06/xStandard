"""Default review gate for procedural data modules.

Decision logic aligned to canonical validation.status vocabulary:
  draft / validated / quarantined / rejected / approved

Gate decisions:
  1. Errors → REJECTED, auto_approved=False
  2. Warnings + low-confidence LLM fields → NOT_REVIEWED (human review)
  3. Warnings only (no LLM concern) → APPROVED with advisory
  4. Clean → APPROVED, auto_approved=True
"""

from __future__ import annotations

from fault_mapper.domain.enums import (
    MappingStrategy,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
)

# ─── Thresholds ──────────────────────────────────────────────────────
_LLM_LOW_CONFIDENCE_THRESHOLD = 0.5
_MAX_LLM_LOW_CONFIDENCE_RATIO = 0.20


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════


def procedural_review_gate(
    module: S1000DProceduralDataModule,
    validation_result: ModuleValidationResult,
) -> ReviewDecision:
    """Evaluate validation results and decide the review disposition."""
    reasons: list[str] = []

    # ── Case 1: Errors → reject ──────────────────────────────────
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

    # ── Case 2 / 3: Warnings only ───────────────────────────────
    if validation_result.has_warnings:
        warning_codes = sorted({
            i.code for i in validation_result.all_issues if i.is_warning
        })
        reasons.append(
            f"Validation warnings: {', '.join(warning_codes)} "
            f"({validation_result.warning_count} total)"
        )

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

    # ── Case 4: Clean validation ─────────────────────────────────
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


def _has_concerning_llm_fields(
    module: S1000DProceduralDataModule,
) -> bool:
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
