"""Procedural persistence-layer fixture builders.

Creates ``S1000DProceduralDataModule`` instances at various lifecycle
stages relevant to persistence testing:

  • APPROVED       → eligible for procedural_trusted collection
  • NOT_REVIEWED   → eligible for procedural_review collection
  • REJECTED       → NOT eligible for persistence

Reuses ``make_valid_procedural_module`` from procedural validation
fixtures for the structurally correct base, then overrides lifecycle fields.
"""

from __future__ import annotations

from typing import Any

from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
)

from tests.fixtures.procedural_validation_fixtures import (
    make_valid_procedural_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  MODULES AT LIFECYCLE STAGES
# ═══════════════════════════════════════════════════════════════════════


def make_approved_procedural_module(**overrides: Any) -> S1000DProceduralDataModule:
    """Module with ``review_status=APPROVED`` — eligible for procedural_trusted."""
    defaults = dict(
        record_id="REC-PROC-APPROVED-001",
        review_status=ReviewStatus.APPROVED,
        mapping_version="1.0.0",
    )
    defaults.update(overrides)
    return make_valid_procedural_module(**defaults)


def make_not_reviewed_procedural_module(**overrides: Any) -> S1000DProceduralDataModule:
    """Module with ``review_status=NOT_REVIEWED`` — eligible for procedural_review."""
    defaults = dict(
        record_id="REC-PROC-REVIEW-001",
        review_status=ReviewStatus.NOT_REVIEWED,
        mapping_version="1.0.0",
    )
    defaults.update(overrides)
    return make_valid_procedural_module(**defaults)


def make_rejected_procedural_module(**overrides: Any) -> S1000DProceduralDataModule:
    """Module with ``review_status=REJECTED`` — NOT eligible for persistence."""
    defaults = dict(
        record_id="REC-PROC-REJECTED-001",
        review_status=ReviewStatus.REJECTED,
    )
    defaults.update(overrides)
    return make_valid_procedural_module(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  ENVELOPE BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_procedural_envelope(
    *,
    record_id: str = "REC-PROC-ENV-001",
    collection: str = "procedural_trusted",
    document: dict[str, object] | None = None,
    validation_status: ValidationStatus = ValidationStatus.APPROVED,
    review_status: ReviewStatus = ReviewStatus.APPROVED,
    mapping_version: str | None = "1.0.0",
    stored_at: str | None = "2026-04-13T12:00:00+00:00",
) -> PersistenceEnvelope:
    """Build a ``PersistenceEnvelope`` for procedural persistence tests."""
    return PersistenceEnvelope(
        record_id=record_id,
        collection=collection,
        document=document or {
            "recordId": record_id,
            "recordType": "S1000D_ProceduralDataModule",
        },
        validation_status=validation_status,
        review_status=review_status,
        mapping_version=mapping_version,
        stored_at=stored_at,
    )
