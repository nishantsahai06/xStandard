"""Persistence-layer fixture builders.

Creates ``S1000DFaultDataModule`` instances at various lifecycle
stages relevant to persistence testing:

  • APPROVED      → eligible for trusted collection
  • REVIEW_REQUIRED → eligible for review collection
  • SCHEMA_FAILED   → NOT eligible for persistence
  • REJECTED        → NOT eligible for persistence
  • STORED          → already persisted (for retrieval tests)

Reuses ``make_valid_fault_reporting_module`` from validation fixtures
for the structurally correct base, then overrides lifecycle fields.
"""

from __future__ import annotations

from typing import Any

from fault_mapper.domain.enums import (
    FaultMode,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.models import S1000DFaultDataModule
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
)

from tests.fixtures.validation_fixtures import (
    make_valid_fault_isolation_module,
    make_valid_fault_reporting_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  MODULES AT LIFECYCLE STAGES
# ═══════════════════════════════════════════════════════════════════════


def make_approved_module(**overrides: Any) -> S1000DFaultDataModule:
    """Module with ``validation_status=APPROVED`` — eligible for trusted."""
    defaults = dict(
        record_id="REC-APPROVED-001",
        validation_status=ValidationStatus.APPROVED,
        review_status=ReviewStatus.APPROVED,
        mapping_version="1.0.0",
    )
    defaults.update(overrides)
    return make_valid_fault_reporting_module(**defaults)


def make_review_required_module(**overrides: Any) -> S1000DFaultDataModule:
    """Module with ``validation_status=REVIEW_REQUIRED`` — eligible for review."""
    defaults = dict(
        record_id="REC-REVIEW-001",
        validation_status=ValidationStatus.REVIEW_REQUIRED,
        review_status=ReviewStatus.NOT_REVIEWED,
        mapping_version="1.0.0",
    )
    defaults.update(overrides)
    return make_valid_fault_reporting_module(**defaults)


def make_schema_failed_module(**overrides: Any) -> S1000DFaultDataModule:
    """Module with ``validation_status=SCHEMA_FAILED`` — NOT eligible."""
    defaults = dict(
        record_id="REC-SCHEMA-FAIL-001",
        validation_status=ValidationStatus.SCHEMA_FAILED,
        review_status=ReviewStatus.NOT_REVIEWED,
    )
    defaults.update(overrides)
    return make_valid_fault_reporting_module(**defaults)


def make_rejected_module(**overrides: Any) -> S1000DFaultDataModule:
    """Module with ``validation_status=REJECTED`` — NOT eligible."""
    defaults = dict(
        record_id="REC-REJECTED-001",
        validation_status=ValidationStatus.REJECTED,
        review_status=ReviewStatus.REJECTED,
    )
    defaults.update(overrides)
    return make_valid_fault_reporting_module(**defaults)


def make_business_rule_failed_module(**overrides: Any) -> S1000DFaultDataModule:
    """Module with ``validation_status=BUSINESS_RULE_FAILED`` — NOT eligible."""
    defaults = dict(
        record_id="REC-BIZ-FAIL-001",
        validation_status=ValidationStatus.BUSINESS_RULE_FAILED,
        review_status=ReviewStatus.NOT_REVIEWED,
    )
    defaults.update(overrides)
    return make_valid_fault_reporting_module(**defaults)


def make_stored_module(**overrides: Any) -> S1000DFaultDataModule:
    """Module with ``validation_status=STORED`` — already persisted."""
    defaults = dict(
        record_id="REC-STORED-001",
        validation_status=ValidationStatus.STORED,
        review_status=ReviewStatus.APPROVED,
        mapping_version="1.0.0",
    )
    defaults.update(overrides)
    return make_valid_fault_reporting_module(**defaults)


def make_approved_isolation_module(**overrides: Any) -> S1000DFaultDataModule:
    """Approved fault-isolation module for mode-diversity testing."""
    defaults = dict(
        record_id="REC-ISO-APPROVED-001",
        validation_status=ValidationStatus.APPROVED,
        review_status=ReviewStatus.APPROVED,
        mapping_version="1.0.0",
    )
    defaults.update(overrides)
    return make_valid_fault_isolation_module(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  ENVELOPE BUILDERS
# ═══════════════════════════════════════════════════════════════════════


def make_envelope(
    *,
    record_id: str = "REC-ENV-001",
    collection: str = "trusted",
    document: dict[str, object] | None = None,
    validation_status: ValidationStatus = ValidationStatus.APPROVED,
    review_status: ReviewStatus = ReviewStatus.APPROVED,
    mapping_version: str | None = "1.0.0",
    stored_at: str | None = "2026-04-13T12:00:00+00:00",
) -> PersistenceEnvelope:
    """Build a ``PersistenceEnvelope`` with sensible defaults."""
    return PersistenceEnvelope(
        record_id=record_id,
        collection=collection,
        document=document or {"recordId": record_id, "recordType": "S1000D_FaultDataModule"},
        validation_status=validation_status,
        review_status=review_status,
        mapping_version=mapping_version,
        stored_at=stored_at,
    )
