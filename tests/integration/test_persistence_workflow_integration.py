"""Real-MongoDB integration tests for persistence + review workflow.

Tests the ``FaultModulePersistenceService`` and
``FaultModuleReviewService`` application services wired to a genuine
MongoDB 7.0 instance via testcontainers.

Sections
────────
A. Persistence service — approved → trusted → STORED
B. Persistence service — review_required → review
C. Persistence service — rejected / failed → not persisted
D. Persistence service — envelope metadata & nested document
E. Review workflow — approve (review → trusted, removed from review)
F. Review workflow — reject (stays in review with REJECTED)
G. Review workflow — missing item → failure
H. Review workflow — repeated approve / reject behaviour
I. End-to-end lifecycle — approved, review+promote, review+reject
J. Counts & listings consistency
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.mongodb_repository import (
    MongoDBFaultModuleRepository,
)
from fault_mapper.application.fault_module_persistence_service import (
    FaultModulePersistenceService,
)
from fault_mapper.application.fault_module_review_service import (
    FaultModuleReviewService,
)
from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.value_objects import PersistenceEnvelope

from tests.fixtures.persistence_fixtures import (
    make_approved_module,
    make_business_rule_failed_module,
    make_rejected_module,
    make_review_required_module,
    make_schema_failed_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  A. PERSISTENCE — APPROVED → TRUSTED → STORED
# ═══════════════════════════════════════════════════════════════════════


class TestPersistApproved:
    """Approved modules go to trusted collection; status transitions to STORED."""

    def test_approved_persists_to_trusted(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="PA-001")
        result = persistence_svc.persist(module)

        assert result.success is True
        assert result.collection == "trusted"
        assert module.validation_status is ValidationStatus.STORED

    def test_approved_envelope_in_trusted_collection(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="PA-002")
        persistence_svc.persist(module)

        env = mongo_repo.get("PA-002", "trusted")
        assert env is not None
        assert env.validation_status is ValidationStatus.APPROVED
        assert env.review_status is ReviewStatus.APPROVED
        assert env.collection == "trusted"

    def test_approved_not_in_review(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="PA-003")
        persistence_svc.persist(module)

        assert mongo_repo.get("PA-003", "review") is None
        assert mongo_repo.count("review") == 0


# ═══════════════════════════════════════════════════════════════════════
#  B. PERSISTENCE — REVIEW_REQUIRED → REVIEW
# ═══════════════════════════════════════════════════════════════════════


class TestPersistReviewRequired:
    """REVIEW_REQUIRED modules go to review collection; no status change."""

    def test_review_required_persists_to_review(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="PR-001")
        result = persistence_svc.persist(module)

        assert result.success is True
        assert result.collection == "review"

    def test_review_required_envelope_in_review_collection(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="PR-002")
        persistence_svc.persist(module)

        env = mongo_repo.get("PR-002", "review")
        assert env is not None
        assert env.validation_status is ValidationStatus.REVIEW_REQUIRED
        assert env.review_status is ReviewStatus.NOT_REVIEWED

    def test_review_required_not_in_trusted(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="PR-003")
        persistence_svc.persist(module)

        assert mongo_repo.get("PR-003", "trusted") is None
        assert mongo_repo.count("trusted") == 0


# ═══════════════════════════════════════════════════════════════════════
#  C. PERSISTENCE — REJECTED / FAILED → NOT PERSISTED
# ═══════════════════════════════════════════════════════════════════════


class TestPersistNotEligible:
    """Modules that fail validation are not persisted."""

    def test_schema_failed_not_persisted(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_schema_failed_module(record_id="PF-001")
        result = persistence_svc.persist(module)

        assert result.success is False
        assert mongo_repo.count("trusted") == 0
        assert mongo_repo.count("review") == 0

    def test_rejected_not_persisted(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_rejected_module(record_id="PF-002")
        result = persistence_svc.persist(module)

        assert result.success is False
        assert mongo_repo.count("trusted") == 0

    def test_business_rule_failed_not_persisted(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_business_rule_failed_module(record_id="PF-003")
        result = persistence_svc.persist(module)

        assert result.success is False
        assert mongo_repo.count("trusted") == 0
        assert mongo_repo.count("review") == 0


# ═══════════════════════════════════════════════════════════════════════
#  D. PERSISTENCE — ENVELOPE METADATA & NESTED DOCUMENT
# ═══════════════════════════════════════════════════════════════════════


class TestPersistEnvelopeContent:
    """Verify persisted envelopes contain expected metadata and document."""

    def test_envelope_contains_record_id(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="PE-001")
        persistence_svc.persist(module)

        env = mongo_repo.get("PE-001", "trusted")
        assert env is not None
        assert env.record_id == "PE-001"

    def test_envelope_contains_mapping_version(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_approved_module(
            record_id="PE-002",
            mapping_version="3.2.1",
        )
        persistence_svc.persist(module)

        env = mongo_repo.get("PE-002", "trusted")
        assert env is not None
        assert env.mapping_version == "3.2.1"

    def test_envelope_contains_stored_at(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="PE-003")
        persistence_svc.persist(module)

        env = mongo_repo.get("PE-003", "trusted")
        assert env is not None
        assert env.stored_at is not None
        assert len(env.stored_at) > 10  # ISO 8601 timestamp

    def test_envelope_document_contains_expected_keys(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="PE-004")
        persistence_svc.persist(module)

        env = mongo_repo.get("PE-004", "trusted")
        assert env is not None
        doc = env.document
        # The serialiser produces these top-level keys at minimum
        assert "recordId" in doc
        assert "recordType" in doc
        assert doc["recordId"] == "PE-004"

    def test_retrieval_via_service_matches_repo(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="PE-005")
        persistence_svc.persist(module)

        via_service = persistence_svc.retrieve("PE-005", "trusted")
        via_repo = mongo_repo.get("PE-005", "trusted")

        assert via_service is not None
        assert via_repo is not None
        assert via_service.record_id == via_repo.record_id
        assert via_service.document == via_repo.document


# ═══════════════════════════════════════════════════════════════════════
#  E. REVIEW WORKFLOW — APPROVE
# ═══════════════════════════════════════════════════════════════════════


class TestReviewApprove:
    """approve() promotes from review → trusted via real MongoDB."""

    def test_approve_moves_to_trusted(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="RA-001")
        persistence_svc.persist(module)

        result = review_svc.approve("RA-001")
        assert result.success is True

        # Now in trusted
        trusted = mongo_repo.get("RA-001", "trusted")
        assert trusted is not None
        assert trusted.validation_status is ValidationStatus.APPROVED
        assert trusted.review_status is ReviewStatus.APPROVED

    def test_approve_removes_from_review(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="RA-002")
        persistence_svc.persist(module)
        assert mongo_repo.count("review") == 1

        review_svc.approve("RA-002")

        assert mongo_repo.get("RA-002", "review") is None
        assert mongo_repo.count("review") == 0

    def test_approve_preserves_document(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="RA-003")
        persistence_svc.persist(module)

        # Capture original document
        original_env = mongo_repo.get("RA-003", "review")
        assert original_env is not None
        orig_doc = original_env.document

        review_svc.approve("RA-003")

        promoted = mongo_repo.get("RA-003", "trusted")
        assert promoted is not None
        assert promoted.document == orig_doc

    def test_approve_sets_stored_at(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="RA-004")
        persistence_svc.persist(module)

        review_svc.approve("RA-004")

        promoted = mongo_repo.get("RA-004", "trusted")
        assert promoted is not None
        assert promoted.stored_at is not None


# ═══════════════════════════════════════════════════════════════════════
#  F. REVIEW WORKFLOW — REJECT
# ═══════════════════════════════════════════════════════════════════════


class TestReviewReject:
    """reject() updates status in review collection via real MongoDB."""

    def test_reject_updates_statuses(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="RR-001")
        persistence_svc.persist(module)

        result = review_svc.reject("RR-001")
        assert result.success is True

        env = mongo_repo.get("RR-001", "review")
        assert env is not None
        assert env.validation_status is ValidationStatus.REJECTED
        assert env.review_status is ReviewStatus.REJECTED

    def test_reject_stays_in_review(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="RR-002")
        persistence_svc.persist(module)

        review_svc.reject("RR-002")

        assert mongo_repo.count("review") == 1
        assert mongo_repo.count("trusted") == 0

    def test_reject_preserves_document(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="RR-003")
        persistence_svc.persist(module)

        original_env = mongo_repo.get("RR-003", "review")
        assert original_env is not None
        orig_doc = original_env.document

        review_svc.reject("RR-003")

        env = mongo_repo.get("RR-003", "review")
        assert env is not None
        assert env.document == orig_doc


# ═══════════════════════════════════════════════════════════════════════
#  G. REVIEW WORKFLOW — MISSING ITEM
# ═══════════════════════════════════════════════════════════════════════


class TestReviewMissingItem:
    """Operations on non-existent review items produce clean failures."""

    def test_approve_missing_returns_failure(
        self,
        review_svc: FaultModuleReviewService,
    ) -> None:
        result = review_svc.approve("DOES-NOT-EXIST")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_reject_missing_returns_failure(
        self,
        review_svc: FaultModuleReviewService,
    ) -> None:
        result = review_svc.reject("DOES-NOT-EXIST")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_get_review_item_missing_returns_none(
        self,
        review_svc: FaultModuleReviewService,
    ) -> None:
        assert review_svc.get_review_item("NOPE") is None


# ═══════════════════════════════════════════════════════════════════════
#  H. REVIEW WORKFLOW — REPEATED OPERATIONS
# ═══════════════════════════════════════════════════════════════════════


class TestReviewRepeatedOps:
    """Repeated approve/reject behaves sensibly."""

    def test_double_approve_second_fails(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
    ) -> None:
        module = make_review_required_module(record_id="RO-001")
        persistence_svc.persist(module)

        r1 = review_svc.approve("RO-001")
        assert r1.success is True

        # Second approve — item no longer in review
        r2 = review_svc.approve("RO-001")
        assert r2.success is False

    def test_double_reject(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        module = make_review_required_module(record_id="RO-002")
        persistence_svc.persist(module)

        r1 = review_svc.reject("RO-002")
        assert r1.success is True
        # Item still in review (with REJECTED status), can reject again
        r2 = review_svc.reject("RO-002")
        assert r2.success is True

    def test_approve_after_reject(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """A rejected item can still be approved (re-review)."""
        module = make_review_required_module(record_id="RO-003")
        persistence_svc.persist(module)

        review_svc.reject("RO-003")
        result = review_svc.approve("RO-003")
        assert result.success is True

        # Now in trusted
        trusted = mongo_repo.get("RO-003", "trusted")
        assert trusted is not None
        assert trusted.validation_status is ValidationStatus.APPROVED


# ═══════════════════════════════════════════════════════════════════════
#  I. END-TO-END LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════


class TestEndToEndLifecycle:
    """Full lifecycle paths exercised against real MongoDB."""

    def test_approved_path(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """APPROVED → persist to trusted → STORED."""
        module = make_approved_module(record_id="E2E-A1")
        result = persistence_svc.persist(module)

        assert result.success is True
        assert module.validation_status is ValidationStatus.STORED
        assert mongo_repo.count("trusted") == 1
        assert mongo_repo.count("review") == 0

    def test_review_then_promote_path(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """REVIEW_REQUIRED → review → approve → trusted."""
        module = make_review_required_module(record_id="E2E-RP1")
        persistence_svc.persist(module)
        assert mongo_repo.count("review") == 1
        assert mongo_repo.count("trusted") == 0

        review_svc.approve("E2E-RP1")
        assert mongo_repo.count("review") == 0
        assert mongo_repo.count("trusted") == 1

        env = mongo_repo.get("E2E-RP1", "trusted")
        assert env is not None
        assert env.validation_status is ValidationStatus.APPROVED
        assert env.review_status is ReviewStatus.APPROVED

    def test_review_then_reject_path(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """REVIEW_REQUIRED → review → reject → stays in review."""
        module = make_review_required_module(record_id="E2E-RJ1")
        persistence_svc.persist(module)

        review_svc.reject("E2E-RJ1")

        assert mongo_repo.count("review") == 1
        assert mongo_repo.count("trusted") == 0

        env = mongo_repo.get("E2E-RJ1", "review")
        assert env is not None
        assert env.validation_status is ValidationStatus.REJECTED

    def test_retrieval_after_promotion(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """Promoted envelope is retrievable via both repo and service."""
        module = make_review_required_module(record_id="E2E-RET1")
        persistence_svc.persist(module)
        review_svc.approve("E2E-RET1")

        via_repo = mongo_repo.get("E2E-RET1", "trusted")
        via_service = persistence_svc.retrieve("E2E-RET1", "trusted")

        assert via_repo is not None
        assert via_service is not None
        assert via_repo.document == via_service.document


# ═══════════════════════════════════════════════════════════════════════
#  J. COUNTS & LISTINGS CONSISTENCY
# ═══════════════════════════════════════════════════════════════════════


class TestCountsAndListings:
    """Counts and listings remain consistent through mixed operations."""

    def test_mixed_persist_then_count(
        self,
        persistence_svc: FaultModulePersistenceService,
        mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        persistence_svc.persist(make_approved_module(record_id="MX-A1"))
        persistence_svc.persist(make_approved_module(record_id="MX-A2"))
        persistence_svc.persist(make_review_required_module(record_id="MX-R1"))

        assert persistence_svc.count_modules("trusted") == 2
        assert persistence_svc.count_modules("review") == 1

    def test_list_after_mixed_persist(
        self,
        persistence_svc: FaultModulePersistenceService,
    ) -> None:
        persistence_svc.persist(make_approved_module(record_id="ML-A1"))
        persistence_svc.persist(make_review_required_module(record_id="ML-R1"))
        persistence_svc.persist(make_review_required_module(record_id="ML-R2"))

        trusted = persistence_svc.list_modules("trusted")
        review = persistence_svc.list_modules("review")

        assert len(trusted) == 1
        assert len(review) == 2

    def test_counts_after_promote(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
    ) -> None:
        persistence_svc.persist(make_review_required_module(record_id="CP-R1"))
        persistence_svc.persist(make_review_required_module(record_id="CP-R2"))
        assert persistence_svc.count_modules("review") == 2

        review_svc.approve("CP-R1")
        assert persistence_svc.count_modules("review") == 1
        assert persistence_svc.count_modules("trusted") == 1

    def test_counts_after_reject(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
    ) -> None:
        persistence_svc.persist(make_review_required_module(record_id="CJ-R1"))
        review_svc.reject("CJ-R1")

        # Still in review (rejected items stay for audit)
        assert persistence_svc.count_modules("review") == 1
        assert persistence_svc.count_modules("trusted") == 0

    def test_review_listing_via_review_service(
        self,
        persistence_svc: FaultModulePersistenceService,
        review_svc: FaultModuleReviewService,
    ) -> None:
        persistence_svc.persist(make_review_required_module(record_id="RL-R1"))
        persistence_svc.persist(make_review_required_module(record_id="RL-R2"))

        items = review_svc.list_review_items()
        assert len(items) == 2
        assert review_svc.count_review_items() == 2
