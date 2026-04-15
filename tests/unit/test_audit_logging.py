"""Tests for Chunk-12 audit-log capture on review rejection/approval.

Covers:
  • reject() writes an REVIEW_REJECTED audit entry with reason + metadata
  • approve() writes an REVIEW_APPROVED audit entry with metadata
  • Missing review item → no orphan audit entries
  • Repeated reject creates separate audit entries
  • Audit repository failure does NOT block the primary operation
  • list_by_record_id retrieves audit entries by record_id
  • No audit entries when audit_repo is None (backwards compatibility)
  • AuditEntry is frozen (immutable)
  • InMemoryAuditRepository basics
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.in_memory_audit_repository import (
    InMemoryAuditRepository,
)
from fault_mapper.application.fault_module_review_service import (
    FaultModuleReviewService,
)
from fault_mapper.domain.enums import (
    AuditEventType,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.value_objects import AuditEntry, PersistenceEnvelope

from tests.fakes.fake_audit_repository import FakeAuditRepository
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.persistence_fixtures import make_envelope


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _review_envelope(
    record_id: str = "AUDIT-001",
    **overrides: object,
) -> PersistenceEnvelope:
    """Build a review-collection envelope."""
    defaults = dict(
        record_id=record_id,
        collection="review",
        validation_status=ValidationStatus.REVIEW_REQUIRED,
        review_status=ReviewStatus.NOT_REVIEWED,
    )
    defaults.update(overrides)
    return make_envelope(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def repo() -> FakeFaultModuleRepository:
    return FakeFaultModuleRepository()


@pytest.fixture()
def audit_repo() -> FakeAuditRepository:
    return FakeAuditRepository()


@pytest.fixture()
def service(
    repo: FakeFaultModuleRepository,
    audit_repo: FakeAuditRepository,
) -> FaultModuleReviewService:
    """Service wired with a fake audit repository."""
    return FaultModuleReviewService(repository=repo, audit_repo=audit_repo)


@pytest.fixture()
def service_no_audit(
    repo: FakeFaultModuleRepository,
) -> FaultModuleReviewService:
    """Service WITHOUT an audit repository (backwards-compat path)."""
    return FaultModuleReviewService(repository=repo)


@pytest.fixture()
def seeded_repo(repo: FakeFaultModuleRepository) -> FakeFaultModuleRepository:
    """Repo with one review item pre-seeded."""
    repo.save(_review_envelope())
    return repo


# ═══════════════════════════════════════════════════════════════════════
#  REJECTION AUDIT TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestRejectAuditEntry:
    """Rejection should capture a structured audit entry."""

    def test_reject_creates_audit_entry(
        self,
        seeded_repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        result = service.reject(
            "AUDIT-001",
            reason="Incorrect mapping",
            performed_by="reviewer@corp.com",
        )
        assert result.success

        entries = audit_repo.list_by_record_id("AUDIT-001")
        assert len(entries) == 1
        entry = entries[0]

        assert entry.record_id == "AUDIT-001"
        assert entry.event_type == AuditEventType.REVIEW_REJECTED
        assert entry.reason == "Incorrect mapping"
        assert entry.performed_by == "reviewer@corp.com"
        assert entry.validation_status == ValidationStatus.REJECTED
        assert entry.review_status == ReviewStatus.REJECTED
        assert entry.collection == "review"
        assert entry.timestamp  # non-empty ISO string

    def test_reject_empty_reason_captured(
        self,
        seeded_repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        """Empty-string reason is still captured (not silently dropped)."""
        service.reject("AUDIT-001")

        entries = audit_repo.list_by_record_id("AUDIT-001")
        assert len(entries) == 1
        assert entries[0].reason == ""

    def test_reject_performed_by_defaults_to_none(
        self,
        seeded_repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        service.reject("AUDIT-001", reason="Bad data")

        entries = audit_repo.list_by_record_id("AUDIT-001")
        assert len(entries) == 1
        assert entries[0].performed_by is None

    def test_reject_missing_item_no_audit_entry(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        """No orphan audit entry when the record doesn't exist."""
        result = service.reject("DOES-NOT-EXIST", reason="Gone")
        assert not result.success
        assert len(audit_repo.append_calls) == 0

    def test_repeated_reject_creates_multiple_entries(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        """Each rejection creates a distinct audit entry."""
        repo.save(_review_envelope())
        service.reject("AUDIT-001", reason="First pass")

        # Re-seed so the item exists again in review
        repo.save(_review_envelope(
            validation_status=ValidationStatus.REJECTED,
            review_status=ReviewStatus.REJECTED,
        ))
        service.reject("AUDIT-001", reason="Second pass")

        entries = audit_repo.list_by_record_id("AUDIT-001")
        assert len(entries) == 2
        assert entries[0].reason == "First pass"
        assert entries[1].reason == "Second pass"


# ═══════════════════════════════════════════════════════════════════════
#  APPROVAL AUDIT TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestApproveAuditEntry:
    """Approval should also capture a structured audit entry."""

    def test_approve_creates_audit_entry(
        self,
        seeded_repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        result = service.approve(
            "AUDIT-001",
            reason="Looks good",
            performed_by="lead@corp.com",
        )
        assert result.success

        entries = audit_repo.list_by_record_id("AUDIT-001")
        assert len(entries) == 1
        entry = entries[0]

        assert entry.record_id == "AUDIT-001"
        assert entry.event_type == AuditEventType.REVIEW_APPROVED
        assert entry.reason == "Looks good"
        assert entry.performed_by == "lead@corp.com"
        assert entry.validation_status == ValidationStatus.APPROVED
        assert entry.review_status == ReviewStatus.APPROVED
        assert entry.collection == "trusted"

    def test_approve_missing_item_no_audit_entry(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        result = service.approve("NOPE", reason="Approved")
        assert not result.success
        assert len(audit_repo.append_calls) == 0


# ═══════════════════════════════════════════════════════════════════════
#  AUDIT FAILURE RESILIENCE
# ═══════════════════════════════════════════════════════════════════════


class TestAuditFailureResilience:
    """Audit repository failures must NOT block the primary operation."""

    def test_reject_succeeds_when_audit_repo_fails(
        self,
        seeded_repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        audit_repo.fail_on_append = True

        result = service.reject(
            "AUDIT-001",
            reason="Failure path",
            performed_by="qa@corp.com",
        )
        assert result.success

        # The call was recorded even though it raised
        assert len(audit_repo.append_calls) == 1
        # But nothing persisted in the inner store
        assert len(audit_repo.all_entries) == 0

    def test_approve_succeeds_when_audit_repo_fails(
        self,
        seeded_repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        audit_repo.fail_on_append = True

        result = service.approve("AUDIT-001", reason="Ship it")
        assert result.success

        assert len(audit_repo.append_calls) == 1
        assert len(audit_repo.all_entries) == 0


# ═══════════════════════════════════════════════════════════════════════
#  BACKWARDS COMPATIBILITY — no audit_repo
# ═══════════════════════════════════════════════════════════════════════


class TestNoAuditRepoBackwardsCompat:
    """When audit_repo is None, nothing changes from Chunk 1–11."""

    def test_reject_without_audit_repo(
        self,
        seeded_repo: FakeFaultModuleRepository,
        service_no_audit: FaultModuleReviewService,
    ) -> None:
        result = service_no_audit.reject("AUDIT-001", reason="Whatever")
        assert result.success

    def test_approve_without_audit_repo(
        self,
        seeded_repo: FakeFaultModuleRepository,
        service_no_audit: FaultModuleReviewService,
    ) -> None:
        result = service_no_audit.approve("AUDIT-001")
        assert result.success


# ═══════════════════════════════════════════════════════════════════════
#  AUDIT ENTRY IMMUTABILITY
# ═══════════════════════════════════════════════════════════════════════


class TestAuditEntryValueObject:
    """``AuditEntry`` is a frozen dataclass — immutable once created."""

    def test_frozen(self) -> None:
        entry = AuditEntry(
            record_id="X",
            event_type=AuditEventType.REVIEW_REJECTED,
            reason="r",
            timestamp="2025-01-01T00:00:00+00:00",
        )
        with pytest.raises(AttributeError):
            entry.reason = "mutated"  # type: ignore[misc]

    def test_default_optional_fields(self) -> None:
        entry = AuditEntry(
            record_id="X",
            event_type=AuditEventType.REVIEW_REJECTED,
            reason="r",
            timestamp="2025-01-01T00:00:00+00:00",
        )
        assert entry.performed_by is None
        assert entry.validation_status is None
        assert entry.review_status is None
        assert entry.collection is None


# ═══════════════════════════════════════════════════════════════════════
#  IN-MEMORY AUDIT REPOSITORY
# ═══════════════════════════════════════════════════════════════════════


class TestInMemoryAuditRepository:
    """Basic behaviour of the in-memory adapter."""

    def test_append_and_retrieve(self) -> None:
        repo = InMemoryAuditRepository()
        entry = AuditEntry(
            record_id="R1",
            event_type=AuditEventType.REVIEW_REJECTED,
            reason="Bad",
            timestamp="2025-01-01T00:00:00+00:00",
        )
        repo.append(entry)

        assert repo.list_by_record_id("R1") == [entry]
        assert repo.list_by_record_id("NOPE") == []

    def test_all_entries(self) -> None:
        repo = InMemoryAuditRepository()
        e1 = AuditEntry(
            record_id="R1",
            event_type=AuditEventType.REVIEW_REJECTED,
            reason="a",
            timestamp="t1",
        )
        e2 = AuditEntry(
            record_id="R2",
            event_type=AuditEventType.REVIEW_APPROVED,
            reason="b",
            timestamp="t2",
        )
        repo.append(e1)
        repo.append(e2)
        assert repo.all_entries == [e1, e2]

    def test_clear(self) -> None:
        repo = InMemoryAuditRepository()
        repo.append(
            AuditEntry(
                record_id="R1",
                event_type=AuditEventType.REVIEW_REJECTED,
                reason="x",
                timestamp="t",
            ),
        )
        repo.clear()
        assert repo.all_entries == []

    def test_multiple_entries_same_record(self) -> None:
        repo = InMemoryAuditRepository()
        for i in range(3):
            repo.append(
                AuditEntry(
                    record_id="SAME",
                    event_type=AuditEventType.REVIEW_REJECTED,
                    reason=f"pass-{i}",
                    timestamp=f"t{i}",
                ),
            )
        assert len(repo.list_by_record_id("SAME")) == 3


# ═══════════════════════════════════════════════════════════════════════
#  END-TO-END: reject → query audit log
# ═══════════════════════════════════════════════════════════════════════


class TestRejectThenQueryAuditLog:
    """Full path: reject a module, then query the audit log."""

    def test_reject_then_list(
        self,
        seeded_repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        service.reject(
            "AUDIT-001",
            reason="Mapping conflicts with spec v2",
            performed_by="qa-bot",
        )

        entries = audit_repo.list_by_record_id("AUDIT-001")
        assert len(entries) == 1

        e = entries[0]
        assert e.event_type == AuditEventType.REVIEW_REJECTED
        assert e.reason == "Mapping conflicts with spec v2"
        assert e.performed_by == "qa-bot"
        assert e.validation_status == ValidationStatus.REJECTED
        assert e.review_status == ReviewStatus.REJECTED
        assert e.collection == "review"

    def test_approve_then_reject_different_records(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReviewService,
    ) -> None:
        """Two different modules — approve one, reject another."""
        repo.save(_review_envelope(record_id="MOD-A"))
        repo.save(_review_envelope(record_id="MOD-B"))

        service.approve("MOD-A", reason="Good", performed_by="lead")
        service.reject("MOD-B", reason="Incorrect", performed_by="lead")

        a_entries = audit_repo.list_by_record_id("MOD-A")
        b_entries = audit_repo.list_by_record_id("MOD-B")

        assert len(a_entries) == 1
        assert a_entries[0].event_type == AuditEventType.REVIEW_APPROVED

        assert len(b_entries) == 1
        assert b_entries[0].event_type == AuditEventType.REVIEW_REJECTED
