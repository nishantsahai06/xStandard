"""Tests for ``FaultModuleReviewService`` — review → trusted promotion.

Covers:
  • approve: happy path, missing item, save failure, delete failure
  • reject: happy path, missing item, save failure
  • get_review_item / list_review_items / count_review_items
  • handoff hook: invoked on approve, failure tolerated
  • idempotency: double-approve, double-reject
"""

from __future__ import annotations

import pytest

from fault_mapper.application.fault_module_review_service import (
    FaultModuleReviewService,
)
from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.value_objects import PersistenceEnvelope

from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.persistence_fixtures import make_envelope


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _review_envelope(
    record_id: str = "REC-REVIEW-001",
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


class _SpyHandoff:
    """Spy double for ``TrustedModuleHandoffPort``."""

    def __init__(self, *, should_fail: bool = False) -> None:
        self.calls: list[PersistenceEnvelope] = []
        self._should_fail = should_fail

    def on_module_stored(self, envelope: PersistenceEnvelope) -> None:
        self.calls.append(envelope)
        if self._should_fail:
            raise RuntimeError("Handoff exploded")


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def repo() -> FakeFaultModuleRepository:
    return FakeFaultModuleRepository()


@pytest.fixture()
def service(repo: FakeFaultModuleRepository) -> FaultModuleReviewService:
    return FaultModuleReviewService(repository=repo)


@pytest.fixture()
def seeded_repo(repo: FakeFaultModuleRepository) -> FakeFaultModuleRepository:
    """Repo with one review item pre-seeded."""
    repo.save(_review_envelope())
    return repo


# ═══════════════════════════════════════════════════════════════════════
#  APPROVE — HAPPY PATH
# ═══════════════════════════════════════════════════════════════════════


class TestApproveHappyPath:
    """Promoting a review item to trusted."""

    def test_approve_returns_success(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        result = svc.approve("REC-REVIEW-001")
        assert result.success is True
        assert result.collection == "trusted"

    def test_approve_creates_trusted_envelope(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        svc.approve("REC-REVIEW-001")

        trusted = seeded_repo.get("REC-REVIEW-001", "trusted")
        assert trusted is not None
        assert trusted.collection == "trusted"
        assert trusted.validation_status is ValidationStatus.APPROVED
        assert trusted.review_status is ReviewStatus.APPROVED

    def test_approve_removes_from_review(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        svc.approve("REC-REVIEW-001")

        assert seeded_repo.get("REC-REVIEW-001", "review") is None
        assert seeded_repo.count("review") == 0

    def test_approve_preserves_document(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        # Capture original document before promotion
        original = seeded_repo.get("REC-REVIEW-001", "review")
        assert original is not None
        orig_doc = original.document

        svc.approve("REC-REVIEW-001")

        trusted = seeded_repo.get("REC-REVIEW-001", "trusted")
        assert trusted is not None
        assert trusted.document == orig_doc

    def test_approve_sets_stored_at(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        svc.approve("REC-REVIEW-001")

        trusted = seeded_repo.get("REC-REVIEW-001", "trusted")
        assert trusted is not None
        assert trusted.stored_at is not None


# ═══════════════════════════════════════════════════════════════════════
#  APPROVE — MISSING ITEM
# ═══════════════════════════════════════════════════════════════════════


class TestApproveMissing:
    """Approving a non-existent review item."""

    def test_approve_missing_returns_failure(
        self, service: FaultModuleReviewService,
    ) -> None:
        result = service.approve("DOES-NOT-EXIST")
        assert result.success is False
        assert "not found" in result.error.lower()


# ═══════════════════════════════════════════════════════════════════════
#  APPROVE — SAVE FAILURE
# ═══════════════════════════════════════════════════════════════════════


class TestApproveSaveFailure:
    """Trusted write fails — review item should NOT be deleted."""

    def test_save_failure_preserves_review_item(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        # Let the first read succeed but fail on save
        seeded_repo.fail_on_save = True

        result = svc.approve("REC-REVIEW-001")
        assert result.success is False

        # Review item should still be there
        assert seeded_repo.get("REC-REVIEW-001", "review") is not None


# ═══════════════════════════════════════════════════════════════════════
#  APPROVE — DELETE FAILURE (best-effort)
# ═══════════════════════════════════════════════════════════════════════


class TestApproveDeleteFailure:
    """Delete from review fails — promotion still succeeds."""

    def test_delete_failure_does_not_fail_promotion(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        seeded_repo.fail_on_delete = True

        result = svc.approve("REC-REVIEW-001")
        # Promotion should still report success (trusted was written)
        assert result.success is True
        # Trusted envelope exists
        assert seeded_repo.get("REC-REVIEW-001", "trusted") is not None


# ═══════════════════════════════════════════════════════════════════════
#  APPROVE — HANDOFF HOOK
# ═══════════════════════════════════════════════════════════════════════


class TestApproveHandoff:
    """TrustedModuleHandoffPort is invoked on promotion."""

    def test_handoff_called_on_approve(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        spy = _SpyHandoff()
        svc = FaultModuleReviewService(
            repository=seeded_repo, handoff=spy,
        )
        svc.approve("REC-REVIEW-001")

        assert len(spy.calls) == 1
        assert spy.calls[0].collection == "trusted"

    def test_handoff_failure_does_not_fail_promotion(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        spy = _SpyHandoff(should_fail=True)
        svc = FaultModuleReviewService(
            repository=seeded_repo, handoff=spy,
        )

        result = svc.approve("REC-REVIEW-001")
        assert result.success is True
        assert len(spy.calls) == 1

    def test_no_handoff_when_none(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        """No crash when handoff is None."""
        svc = FaultModuleReviewService(
            repository=seeded_repo, handoff=None,
        )
        result = svc.approve("REC-REVIEW-001")
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════════
#  REJECT — HAPPY PATH
# ═══════════════════════════════════════════════════════════════════════


class TestRejectHappyPath:
    """Rejecting a review item keeps it in review with REJECTED status."""

    def test_reject_returns_success(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        result = svc.reject("REC-REVIEW-001")
        assert result.success is True

    def test_reject_updates_statuses(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        svc.reject("REC-REVIEW-001")

        env = seeded_repo.get("REC-REVIEW-001", "review")
        assert env is not None
        assert env.validation_status is ValidationStatus.REJECTED
        assert env.review_status is ReviewStatus.REJECTED

    def test_reject_stays_in_review_collection(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        svc.reject("REC-REVIEW-001")

        # Still in review collection
        assert seeded_repo.count("review") == 1
        # Not in trusted
        assert seeded_repo.count("trusted") == 0

    def test_reject_preserves_document(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        original = seeded_repo.get("REC-REVIEW-001", "review")
        assert original is not None
        orig_doc = original.document

        svc.reject("REC-REVIEW-001")

        env = seeded_repo.get("REC-REVIEW-001", "review")
        assert env is not None
        assert env.document == orig_doc


# ═══════════════════════════════════════════════════════════════════════
#  REJECT — MISSING / FAILURE
# ═══════════════════════════════════════════════════════════════════════


class TestRejectEdgeCases:

    def test_reject_missing_returns_failure(
        self, service: FaultModuleReviewService,
    ) -> None:
        result = service.reject("DOES-NOT-EXIST")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_reject_save_failure(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        seeded_repo.fail_on_save = True

        result = svc.reject("REC-REVIEW-001")
        assert result.success is False


# ═══════════════════════════════════════════════════════════════════════
#  READ OPERATIONS
# ═══════════════════════════════════════════════════════════════════════


class TestReadOperations:
    """get_review_item, list_review_items, count_review_items."""

    def test_get_review_item_found(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        env = svc.get_review_item("REC-REVIEW-001")
        assert env is not None
        assert env.record_id == "REC-REVIEW-001"

    def test_get_review_item_not_found(
        self, service: FaultModuleReviewService,
    ) -> None:
        env = service.get_review_item("NOPE")
        assert env is None

    def test_list_review_items_empty(
        self, service: FaultModuleReviewService,
    ) -> None:
        items = service.list_review_items()
        assert items == []

    def test_list_review_items_populated(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        # Add a second item
        seeded_repo.save(_review_envelope(record_id="REC-REVIEW-002"))
        svc = FaultModuleReviewService(repository=seeded_repo)

        items = svc.list_review_items()
        assert len(items) == 2

    def test_list_review_items_pagination(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        seeded_repo.save(_review_envelope(record_id="REC-REVIEW-002"))
        seeded_repo.save(_review_envelope(record_id="REC-REVIEW-003"))
        svc = FaultModuleReviewService(repository=seeded_repo)

        page = svc.list_review_items(limit=2, offset=1)
        assert len(page) == 2

    def test_count_review_items_empty(
        self, service: FaultModuleReviewService,
    ) -> None:
        assert service.count_review_items() == 0

    def test_count_review_items_populated(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        assert svc.count_review_items() == 1


# ═══════════════════════════════════════════════════════════════════════
#  IDEMPOTENCY
# ═══════════════════════════════════════════════════════════════════════


class TestIdempotency:
    """Double operations produce sensible results."""

    def test_double_approve_second_fails(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        result1 = svc.approve("REC-REVIEW-001")
        assert result1.success is True

        # Second approve — item no longer in review
        result2 = svc.approve("REC-REVIEW-001")
        assert result2.success is False
        assert "not found" in result2.error.lower()

    def test_double_reject_second_still_rejects(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        svc = FaultModuleReviewService(repository=seeded_repo)
        result1 = svc.reject("REC-REVIEW-001")
        assert result1.success is True

        # Second reject — item still in review (with REJECTED status)
        result2 = svc.reject("REC-REVIEW-001")
        assert result2.success is True

    def test_approve_after_reject_fails(
        self, seeded_repo: FakeFaultModuleRepository,
    ) -> None:
        """Rejected item can still be approved (it's still in review)."""
        svc = FaultModuleReviewService(repository=seeded_repo)
        svc.reject("REC-REVIEW-001")

        # The item is still in review — approve should succeed
        result = svc.approve("REC-REVIEW-001")
        assert result.success is True

        # Now it's in trusted with APPROVED status
        trusted = seeded_repo.get("REC-REVIEW-001", "trusted")
        assert trusted is not None
        assert trusted.validation_status is ValidationStatus.APPROVED


# ═══════════════════════════════════════════════════════════════════════
#  MULTIPLE ITEMS
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleItems:
    """Operations on distinct items don't interfere."""

    def test_approve_one_reject_another(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(_review_envelope(record_id="MOD-A"))
        repo.save(_review_envelope(record_id="MOD-B"))
        svc = FaultModuleReviewService(repository=repo)

        result_a = svc.approve("MOD-A")
        result_b = svc.reject("MOD-B")

        assert result_a.success is True
        assert result_b.success is True

        # MOD-A in trusted, removed from review
        assert repo.get("MOD-A", "trusted") is not None
        assert repo.get("MOD-A", "review") is None

        # MOD-B still in review with REJECTED
        env_b = repo.get("MOD-B", "review")
        assert env_b is not None
        assert env_b.validation_status is ValidationStatus.REJECTED
