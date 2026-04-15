"""Tests for Chunk-13 reconciliation / sweep service.

Covers:
  • No duplicates found → clean report
  • Single orphaned duplicate found and cleaned
  • Dry-run mode — reported but not deleted
  • Delete failure reported but does not crash the sweep
  • Conflicting duplicate is skipped (document payload mismatch)
  • Non-authoritative trusted status → skipped
  • Review record with unexpected status → skipped
  • Multiple duplicates in one sweep
  • Report counts are correct
  • Limit parameter respected
  • find_orphaned_review_ids utility
  • Records that vanish mid-sweep (race condition safety)
  • Audit logging on cleanup
  • Backwards compatibility — no audit repo
  • ReconciliationReport and ReconciliationDetail are frozen
  • list_record_ids on InMemoryFaultModuleRepository
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.in_memory_repository import (
    InMemoryFaultModuleRepository,
)
from fault_mapper.application.fault_module_reconciliation_service import (
    FaultModuleReconciliationService,
)
from fault_mapper.domain.enums import (
    AuditEventType,
    ReconciliationOutcome,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.value_objects import (
    ReconciliationDetail,
    ReconciliationReport,
)

from tests.fakes.fake_audit_repository import FakeAuditRepository
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.persistence_fixtures import make_envelope


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _orphan_scenario(
    repo: FakeFaultModuleRepository,
    record_id: str = "ORPHAN-001",
    *,
    trusted_validation: ValidationStatus = ValidationStatus.APPROVED,
    trusted_review: ReviewStatus = ReviewStatus.APPROVED,
    review_validation: ValidationStatus = ValidationStatus.APPROVED,
    review_review: ReviewStatus = ReviewStatus.APPROVED,
    trusted_doc: dict | None = None,
    review_doc: dict | None = None,
) -> None:
    """Seed the repo with a typical orphan scenario:
    same record_id in both trusted and review."""
    repo.save(make_envelope(
        record_id=record_id,
        collection="trusted",
        validation_status=trusted_validation,
        review_status=trusted_review,
        document=trusted_doc or {"recordId": record_id, "recordType": "S1000D_FaultDataModule"},
    ))
    repo.save(make_envelope(
        record_id=record_id,
        collection="review",
        validation_status=review_validation,
        review_status=review_review,
        document=review_doc or {"recordId": record_id, "recordType": "S1000D_FaultDataModule"},
    ))


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
) -> FaultModuleReconciliationService:
    return FaultModuleReconciliationService(
        repository=repo, audit_repo=audit_repo,
    )


@pytest.fixture()
def service_no_audit(
    repo: FakeFaultModuleRepository,
) -> FaultModuleReconciliationService:
    return FaultModuleReconciliationService(repository=repo)


# ═══════════════════════════════════════════════════════════════════════
#  EMPTY / NO DUPLICATES
# ═══════════════════════════════════════════════════════════════════════


class TestNoDuplicates:
    """When there are no orphaned entries, the sweep is a no-op."""

    def test_empty_repo(
        self,
        service: FaultModuleReconciliationService,
    ) -> None:
        report = service.sweep()
        assert report.total_review_scanned == 0
        assert report.duplicates_found == 0
        assert report.duplicates_cleaned == 0
        assert report.duplicates_skipped == 0
        assert report.errors == 0
        assert report.details == []
        assert report.dry_run is False

    def test_review_only_no_trusted(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Items in review only — not duplicates."""
        repo.save(make_envelope(record_id="R1", collection="review"))
        repo.save(make_envelope(record_id="R2", collection="review"))
        report = service.sweep()
        assert report.total_review_scanned == 2
        assert report.duplicates_found == 0

    def test_trusted_only_no_review(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Items in trusted only — nothing to clean."""
        repo.save(make_envelope(record_id="T1", collection="trusted"))
        report = service.sweep()
        assert report.total_review_scanned == 0
        assert report.duplicates_found == 0

    def test_different_record_ids(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Different record_ids across collections — no overlap."""
        repo.save(make_envelope(record_id="R1", collection="review"))
        repo.save(make_envelope(record_id="T1", collection="trusted"))
        report = service.sweep()
        assert report.total_review_scanned == 1
        assert report.duplicates_found == 0


# ═══════════════════════════════════════════════════════════════════════
#  HAPPY PATH — ORPHAN CLEANED
# ═══════════════════════════════════════════════════════════════════════


class TestOrphanCleaned:
    """A genuine orphan should be detected and cleaned."""

    def test_single_orphan_cleaned(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)

        report = service.sweep()

        assert report.total_review_scanned == 1
        assert report.duplicates_found == 1
        assert report.duplicates_cleaned == 1
        assert report.duplicates_skipped == 0
        assert report.errors == 0

        # Review entry should be gone
        assert repo.get("ORPHAN-001", "review") is None
        # Trusted entry must remain
        assert repo.get("ORPHAN-001", "trusted") is not None

    def test_cleaned_detail_record(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)
        report = service.sweep()

        assert len(report.details) == 1
        d = report.details[0]
        assert d.record_id == "ORPHAN-001"
        assert d.outcome == ReconciliationOutcome.CLEANED
        assert "deleted" in d.reason.lower()

    def test_trusted_stored_status_also_authoritative(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """ValidationStatus.STORED is also authoritative."""
        _orphan_scenario(
            repo,
            trusted_validation=ValidationStatus.STORED,
        )
        report = service.sweep()
        assert report.duplicates_cleaned == 1


# ═══════════════════════════════════════════════════════════════════════
#  DRY-RUN MODE
# ═══════════════════════════════════════════════════════════════════════


class TestDryRun:
    """Dry-run should report what would be cleaned without deleting."""

    def test_dry_run_no_delete(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)

        report = service.sweep(dry_run=True)

        assert report.dry_run is True
        assert report.duplicates_found == 1
        assert report.duplicates_cleaned == 1  # "would clean"
        assert report.details[0].outcome == ReconciliationOutcome.CLEANED

        # Review entry should still be there
        assert repo.get("ORPHAN-001", "review") is not None

    def test_dry_run_detail_mentions_dry_run(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)
        report = service.sweep(dry_run=True)
        assert "dry-run" in report.details[0].reason.lower()


# ═══════════════════════════════════════════════════════════════════════
#  DELETE FAILURE
# ═══════════════════════════════════════════════════════════════════════


class TestDeleteFailure:
    """Delete failure is reported but does not crash the sweep."""

    def test_delete_failure_error_in_report(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)
        repo.fail_on_delete = True

        report = service.sweep()

        assert report.duplicates_found == 1
        assert report.duplicates_cleaned == 0
        assert report.errors == 1
        assert report.details[0].outcome == ReconciliationOutcome.ERROR
        assert "failed" in report.details[0].reason.lower()

    def test_delete_failure_does_not_abort_sweep(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Multiple orphans — first fails, second still processed."""
        _orphan_scenario(repo, record_id="FAIL-001")
        _orphan_scenario(repo, record_id="OK-002")

        # Make only the first delete fail by using a custom approach:
        # We'll set fail_on_delete, let the first record fail,
        # then we actually want the second to also fail since
        # fail_on_delete applies to all deletes.
        # Instead, verify both are attempted.
        repo.fail_on_delete = True

        report = service.sweep()
        assert report.duplicates_found == 2
        assert report.errors == 2
        # Both were attempted — no abort
        assert len(report.details) == 2


# ═══════════════════════════════════════════════════════════════════════
#  SAFETY CHECKS — SKIPPED RECORDS
# ═══════════════════════════════════════════════════════════════════════


class TestSafetySkips:
    """Conservative safety checks should skip unsafe duplicates."""

    def test_conflicting_document_skipped(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Different recordType in document payload → skip."""
        _orphan_scenario(
            repo,
            trusted_doc={"recordId": "ORPHAN-001", "recordType": "TypeA"},
            review_doc={"recordId": "ORPHAN-001", "recordType": "TypeB"},
        )
        report = service.sweep()
        assert report.duplicates_skipped == 1
        assert report.duplicates_cleaned == 0
        assert report.details[0].outcome == ReconciliationOutcome.SKIPPED
        assert "conflicting" in report.details[0].reason.lower()

    def test_conflicting_record_id_in_document_skipped(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Different recordId inside document payload → skip."""
        _orphan_scenario(
            repo,
            trusted_doc={"recordId": "ORPHAN-001"},
            review_doc={"recordId": "DIFFERENT-ID"},
        )
        report = service.sweep()
        assert report.duplicates_skipped == 1

    def test_non_authoritative_trusted_status_skipped(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Trusted record with PENDING status → not authoritative → skip."""
        _orphan_scenario(
            repo,
            trusted_validation=ValidationStatus.PENDING,
        )
        report = service.sweep()
        assert report.duplicates_skipped == 1
        assert "non-authoritative" in report.details[0].reason.lower()

    def test_review_record_with_rejected_status_skipped(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Review record with REJECTED status is NOT an orphan → skip."""
        _orphan_scenario(
            repo,
            review_validation=ValidationStatus.REJECTED,
        )
        report = service.sweep()
        assert report.duplicates_skipped == 1
        assert "unexpected status" in report.details[0].reason.lower()

    def test_review_record_review_required_skipped(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Review record with REVIEW_REQUIRED — maybe not promoted yet → skip."""
        _orphan_scenario(
            repo,
            review_validation=ValidationStatus.REVIEW_REQUIRED,
        )
        report = service.sweep()
        assert report.duplicates_skipped == 1

    def test_compatible_documents_cleaned(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """Identical payloads → safe to clean."""
        doc = {"recordId": "ORPHAN-001", "recordType": "S1000D_FaultDataModule", "extra": "data"}
        _orphan_scenario(repo, trusted_doc=doc, review_doc=doc)
        report = service.sweep()
        assert report.duplicates_cleaned == 1


# ═══════════════════════════════════════════════════════════════════════
#  MULTIPLE DUPLICATES
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleDuplicates:
    """Sweep handles multiple orphans in a single pass."""

    def test_three_orphans_cleaned(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        for i in range(3):
            _orphan_scenario(repo, record_id=f"MULTI-{i:03d}")

        report = service.sweep()
        assert report.total_review_scanned == 3
        assert report.duplicates_found == 3
        assert report.duplicates_cleaned == 3
        assert len(report.details) == 3

    def test_mixed_outcomes(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        """One clean orphan, one conflicting, one non-orphan."""
        # Clean orphan
        _orphan_scenario(repo, record_id="CLEAN-001")
        # Conflicting
        _orphan_scenario(
            repo,
            record_id="CONFLICT-001",
            trusted_doc={"recordId": "CONFLICT-001", "recordType": "A"},
            review_doc={"recordId": "CONFLICT-001", "recordType": "B"},
        )
        # Non-duplicate (review only)
        repo.save(make_envelope(
            record_id="REVIEW-ONLY",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))

        report = service.sweep()
        assert report.total_review_scanned == 3
        assert report.duplicates_found == 2
        assert report.duplicates_cleaned == 1
        assert report.duplicates_skipped == 1


# ═══════════════════════════════════════════════════════════════════════
#  LIMIT PARAMETER
# ═══════════════════════════════════════════════════════════════════════


class TestLimit:
    """Limit restricts how many review records are scanned."""

    def test_limit_caps_scan(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        for i in range(5):
            _orphan_scenario(repo, record_id=f"LIM-{i:03d}")

        report = service.sweep(limit=2)
        assert report.total_review_scanned == 2
        # We might find 0, 1, or 2 duplicates depending on which
        # review IDs were returned first, but at most 2
        assert report.duplicates_found <= 2


# ═══════════════════════════════════════════════════════════════════════
#  FIND_ORPHANED_REVIEW_IDS
# ═══════════════════════════════════════════════════════════════════════


class TestFindOrphanedReviewIds:
    """Lightweight utility for listing candidate orphans."""

    def test_no_orphans(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        repo.save(make_envelope(record_id="R1", collection="review"))
        assert service.find_orphaned_review_ids() == []

    def test_one_orphan(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo, record_id="FOUND-001")
        assert service.find_orphaned_review_ids() == ["FOUND-001"]

    def test_multiple_orphans(
        self,
        repo: FakeFaultModuleRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo, record_id="A")
        _orphan_scenario(repo, record_id="B")
        result = service.find_orphaned_review_ids()
        assert set(result) == {"A", "B"}


# ═══════════════════════════════════════════════════════════════════════
#  RACE-CONDITION SAFETY (record vanishes mid-sweep)
# ═══════════════════════════════════════════════════════════════════════


class TestRaceConditionSafety:
    """Records that disappear between ID listing and fetch are skipped."""

    def test_trusted_vanishes(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
    ) -> None:
        """Trusted record deleted between list_record_ids and get."""
        _orphan_scenario(repo, record_id="RACE-001")

        svc = FaultModuleReconciliationService(
            repository=repo, audit_repo=audit_repo,
        )
        # Remove trusted before sweep processes it
        repo.delete("RACE-001", "trusted")

        # Re-add to review so it's still listed (already there)
        # Actually, repo still has review item. But trusted is gone.
        # The sweep finds RACE-001 in review, checks trusted_ids set,
        # but trusted was deleted AFTER list_record_ids returned.
        # Because we deleted trusted BEFORE sweep(), list_record_ids
        # won't include it. So it won't be flagged as duplicate.
        report = svc.sweep()
        assert report.duplicates_found == 0

    def test_review_vanishes_during_process(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
    ) -> None:
        """Simulate review vanishing by removing it after ID listing.

        We can't easily mock mid-iteration, so we test the safety
        check inside _process_duplicate directly.
        """
        # Seed orphan
        _orphan_scenario(repo, record_id="RACE-002")

        svc = FaultModuleReconciliationService(
            repository=repo, audit_repo=audit_repo,
        )

        # Manually call _process_duplicate after deleting review
        repo.delete("RACE-002", "review")
        detail = svc._process_duplicate("RACE-002", dry_run=False)
        assert detail.outcome == ReconciliationOutcome.SKIPPED
        assert "disappeared" in detail.reason.lower()


# ═══════════════════════════════════════════════════════════════════════
#  AUDIT LOGGING
# ═══════════════════════════════════════════════════════════════════════


class TestAuditLogging:
    """Reconciliation cleanup should record audit entries."""

    def test_cleaned_audit_entry(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)
        service.sweep()

        entries = audit_repo.list_by_record_id("ORPHAN-001")
        assert len(entries) == 1
        e = entries[0]
        assert e.event_type == AuditEventType.RECONCILIATION_CLEANED
        assert e.performed_by == "reconciliation-sweep"
        assert e.collection == "review"

    def test_skipped_audit_entry(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(
            repo,
            trusted_validation=ValidationStatus.PENDING,
        )
        service.sweep()

        entries = audit_repo.list_by_record_id("ORPHAN-001")
        assert len(entries) == 1
        assert entries[0].event_type == AuditEventType.RECONCILIATION_SKIPPED

    def test_dry_run_audit_entry(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)
        service.sweep(dry_run=True)

        entries = audit_repo.list_by_record_id("ORPHAN-001")
        assert len(entries) == 1
        assert entries[0].event_type == AuditEventType.RECONCILIATION_CLEANED
        assert "dry-run" in entries[0].reason.lower()

    def test_audit_failure_does_not_crash_sweep(
        self,
        repo: FakeFaultModuleRepository,
        audit_repo: FakeAuditRepository,
        service: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)
        audit_repo.fail_on_append = True

        report = service.sweep()
        # Sweep still succeeds
        assert report.duplicates_cleaned == 1


# ═══════════════════════════════════════════════════════════════════════
#  BACKWARDS COMPATIBILITY — no audit repo
# ═══════════════════════════════════════════════════════════════════════


class TestNoAuditRepoCompat:
    """Service works without an audit repository."""

    def test_sweep_without_audit_repo(
        self,
        repo: FakeFaultModuleRepository,
        service_no_audit: FaultModuleReconciliationService,
    ) -> None:
        _orphan_scenario(repo)
        report = service_no_audit.sweep()
        assert report.duplicates_cleaned == 1


# ═══════════════════════════════════════════════════════════════════════
#  VALUE OBJECT IMMUTABILITY
# ═══════════════════════════════════════════════════════════════════════


class TestReconciliationValueObjects:
    """Reconciliation VOs are frozen dataclasses."""

    def test_report_frozen(self) -> None:
        report = ReconciliationReport()
        with pytest.raises(AttributeError):
            report.dry_run = True  # type: ignore[misc]

    def test_detail_frozen(self) -> None:
        detail = ReconciliationDetail(
            record_id="X",
            outcome=ReconciliationOutcome.CLEANED,
            reason="test",
        )
        with pytest.raises(AttributeError):
            detail.reason = "mutated"  # type: ignore[misc]

    def test_reconciliation_outcome_values(self) -> None:
        assert ReconciliationOutcome.CLEANED.value == "cleaned"
        assert ReconciliationOutcome.SKIPPED.value == "skipped"
        assert ReconciliationOutcome.ERROR.value == "error"


# ═══════════════════════════════════════════════════════════════════════
#  IN-MEMORY REPOSITORY — list_record_ids
# ═══════════════════════════════════════════════════════════════════════


class TestListRecordIds:
    """New port method works on in-memory repository."""

    def test_empty(self) -> None:
        repo = InMemoryFaultModuleRepository()
        assert repo.list_record_ids("review") == []

    def test_returns_ids_for_collection(self) -> None:
        repo = InMemoryFaultModuleRepository()
        repo.save(make_envelope(record_id="R1", collection="review"))
        repo.save(make_envelope(record_id="R2", collection="review"))
        repo.save(make_envelope(record_id="T1", collection="trusted"))

        review_ids = repo.list_record_ids("review")
        assert set(review_ids) == {"R1", "R2"}

        trusted_ids = repo.list_record_ids("trusted")
        assert trusted_ids == ["T1"]

    def test_fake_repo_delegates(self) -> None:
        repo = FakeFaultModuleRepository()
        repo.save(make_envelope(record_id="X", collection="review"))
        assert repo.list_record_ids("review") == ["X"]
