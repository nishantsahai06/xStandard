"""Tests for ``FaultModulePersistenceService``.

Covers:
  • Routing: APPROVED → trusted, REVIEW_REQUIRED → review
  • Rejection: SCHEMA_FAILED, BUSINESS_RULE_FAILED, REJECTED, PENDING, STORED
  • Lifecycle: APPROVED → STORED transition on success
  • Error handling: serialiser failure, repository failure
  • Retrieve / list / count delegation
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.models import S1000DFaultDataModule
from fault_mapper.application.fault_module_persistence_service import (
    FaultModulePersistenceService,
)
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.persistence_fixtures import (
    make_approved_module,
    make_approved_isolation_module,
    make_business_rule_failed_module,
    make_rejected_module,
    make_review_required_module,
    make_schema_failed_module,
    make_stored_module,
    make_envelope,
)


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_repo() -> FakeFaultModuleRepository:
    return FakeFaultModuleRepository()


@pytest.fixture
def service(fake_repo: FakeFaultModuleRepository) -> FaultModulePersistenceService:
    return FaultModulePersistenceService(repository=fake_repo)


# ═══════════════════════════════════════════════════════════════════════
#  A. ROUTING — APPROVED → TRUSTED
# ═══════════════════════════════════════════════════════════════════════


class TestPersistApproved:
    """APPROVED modules route to the 'trusted' collection."""

    def test_approved_reporting_persists_to_trusted(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_module()
        result = service.persist(module)

        assert result.success is True
        assert result.collection == "trusted"
        assert result.record_id == module.record_id
        assert result.stored_at is not None
        assert len(fake_repo.save_calls) == 1
        assert fake_repo.save_calls[0].collection == "trusted"

    def test_approved_isolation_persists_to_trusted(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_isolation_module()
        result = service.persist(module)

        assert result.success is True
        assert result.collection == "trusted"

    def test_approved_module_transitions_to_stored(
        self, service: FaultModulePersistenceService,
    ) -> None:
        module = make_approved_module()
        assert module.validation_status is ValidationStatus.APPROVED

        service.persist(module)

        assert module.validation_status is ValidationStatus.STORED

    def test_envelope_carries_correct_metadata(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_module(mapping_version="2.0.0")
        service.persist(module)

        env = fake_repo.save_calls[0]
        assert env.mapping_version == "2.0.0"
        assert env.validation_status is ValidationStatus.APPROVED
        assert env.review_status is ReviewStatus.APPROVED
        assert env.stored_at is not None
        assert isinstance(env.document, dict)
        assert env.document["recordId"] == module.record_id

    def test_envelope_document_contains_serialised_module(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_module()
        service.persist(module)

        doc = fake_repo.save_calls[0].document
        assert "recordType" in doc
        assert doc["recordType"] == "S1000D_FaultDataModule"
        assert "header" in doc
        assert "content" in doc


# ═══════════════════════════════════════════════════════════════════════
#  B. ROUTING — REVIEW_REQUIRED → REVIEW
# ═══════════════════════════════════════════════════════════════════════


class TestPersistReviewRequired:
    """REVIEW_REQUIRED modules route to the 'review' collection."""

    def test_review_required_persists_to_review(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_review_required_module()
        result = service.persist(module)

        assert result.success is True
        assert result.collection == "review"
        assert len(fake_repo.save_calls) == 1
        assert fake_repo.save_calls[0].collection == "review"

    def test_review_required_does_not_transition_to_stored(
        self, service: FaultModulePersistenceService,
    ) -> None:
        module = make_review_required_module()
        service.persist(module)

        # REVIEW_REQUIRED stays as-is (not promoted to STORED)
        assert module.validation_status is ValidationStatus.REVIEW_REQUIRED

    def test_review_required_envelope_metadata(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_review_required_module()
        service.persist(module)

        env = fake_repo.save_calls[0]
        assert env.validation_status is ValidationStatus.REVIEW_REQUIRED
        assert env.review_status is ReviewStatus.NOT_REVIEWED


# ═══════════════════════════════════════════════════════════════════════
#  C. REJECTION — INELIGIBLE STATUSES
# ═══════════════════════════════════════════════════════════════════════


class TestPersistRejected:
    """Modules with non-persistable statuses are rejected."""

    @pytest.mark.parametrize(
        "module_factory,expected_status",
        [
            (make_schema_failed_module, ValidationStatus.SCHEMA_FAILED),
            (make_business_rule_failed_module, ValidationStatus.BUSINESS_RULE_FAILED),
            (make_rejected_module, ValidationStatus.REJECTED),
            (make_stored_module, ValidationStatus.STORED),
        ],
        ids=["schema_failed", "biz_rule_failed", "rejected", "already_stored"],
    )
    def test_ineligible_status_returns_failure(
        self,
        service: FaultModulePersistenceService,
        fake_repo: FakeFaultModuleRepository,
        module_factory,
        expected_status: ValidationStatus,
    ) -> None:
        module = module_factory()
        result = service.persist(module)

        assert result.success is False
        assert result.collection == ""
        assert "only APPROVED and REVIEW_REQUIRED" in (result.error or "")
        assert len(fake_repo.save_calls) == 0

    def test_pending_module_is_rejected(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_module(
            record_id="REC-PENDING",
            validation_status=ValidationStatus.PENDING,
        )
        result = service.persist(module)

        assert result.success is False
        assert len(fake_repo.save_calls) == 0


# ═══════════════════════════════════════════════════════════════════════
#  D. ERROR HANDLING
# ═══════════════════════════════════════════════════════════════════════


class TestPersistErrors:
    """Error handling for serialiser and repository failures."""

    def test_serialiser_failure_returns_error_result(
        self, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        def bad_serializer(_module):
            raise ValueError("boom")

        svc = FaultModulePersistenceService(
            repository=fake_repo,
            serializer=bad_serializer,
        )
        module = make_approved_module()
        result = svc.persist(module)

        assert result.success is False
        assert "Serialisation failed" in (result.error or "")
        assert result.collection == "trusted"
        # Module should NOT have transitioned to STORED
        assert module.validation_status is ValidationStatus.APPROVED

    def test_repository_failure_returns_error_result(
        self, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        fake_repo.fail_on_save = True
        svc = FaultModulePersistenceService(repository=fake_repo)

        module = make_approved_module()
        result = svc.persist(module)

        assert result.success is False
        assert "Simulated repository failure" in (result.error or "")
        # Module should NOT have transitioned to STORED
        assert module.validation_status is ValidationStatus.APPROVED

    def test_repository_exception_is_caught(
        self,
    ) -> None:
        """Repository that raises an exception (not returns failure)."""

        class ExplodingRepo:
            def save(self, _envelope):
                raise RuntimeError("connection lost")

            def get(self, _record_id, _collection):
                return None

            def list_by_collection(self, _collection, *, limit=100, offset=0):
                return []

            def count(self, _collection):
                return 0

        svc = FaultModulePersistenceService(repository=ExplodingRepo())
        module = make_approved_module()
        result = svc.persist(module)

        assert result.success is False
        assert "Repository write failed" in (result.error or "")


# ═══════════════════════════════════════════════════════════════════════
#  E. MULTIPLE PERSIST OPERATIONS
# ═══════════════════════════════════════════════════════════════════════


class TestMultiplePersists:
    """Persisting multiple modules accumulates in the repository."""

    def test_two_approved_modules(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        m1 = make_approved_module(record_id="REC-A")
        m2 = make_approved_module(record_id="REC-B")
        r1 = service.persist(m1)
        r2 = service.persist(m2)

        assert r1.success and r2.success
        assert fake_repo.count("trusted") == 2

    def test_mixed_routing(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        approved = make_approved_module(record_id="REC-T")
        review = make_review_required_module(record_id="REC-R")
        rejected = make_rejected_module(record_id="REC-X")

        service.persist(approved)
        service.persist(review)
        service.persist(rejected)

        assert fake_repo.count("trusted") == 1
        assert fake_repo.count("review") == 1
        assert len(fake_repo.save_calls) == 2  # rejected was not saved

    def test_upsert_replaces_existing(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        m1 = make_approved_module(record_id="REC-UPSERT")
        service.persist(m1)
        assert fake_repo.count("trusted") == 1

        # Re-persist same record_id — different version
        m2 = make_approved_module(
            record_id="REC-UPSERT",
            mapping_version="2.0.0",
        )
        # Reset status back to APPROVED for re-persist
        m2.validation_status = ValidationStatus.APPROVED
        service.persist(m2)

        # Still just 1 doc (upserted)
        assert fake_repo.count("trusted") == 1
        env = fake_repo.get("REC-UPSERT", "trusted")
        assert env is not None
        assert env.mapping_version == "2.0.0"


# ═══════════════════════════════════════════════════════════════════════
#  F. RETRIEVE / LIST / COUNT
# ═══════════════════════════════════════════════════════════════════════


class TestRetrieveAndList:
    """Service delegates read operations to the repository."""

    def test_retrieve_existing(
        self, service: FaultModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_module(record_id="REC-GET")
        service.persist(module)

        env = service.retrieve("REC-GET", "trusted")
        assert env is not None
        assert env.record_id == "REC-GET"

    def test_retrieve_missing_returns_none(
        self, service: FaultModulePersistenceService,
    ) -> None:
        assert service.retrieve("NONEXISTENT", "trusted") is None

    def test_list_modules(
        self, service: FaultModulePersistenceService,
    ) -> None:
        for i in range(5):
            m = make_approved_module(record_id=f"REC-LIST-{i}")
            # Reset STORED back to APPROVED for next persist
            service.persist(m)

        result = service.list_modules("trusted", limit=3)
        assert len(result) == 3

    def test_count_modules(
        self, service: FaultModulePersistenceService,
    ) -> None:
        for i in range(3):
            service.persist(make_approved_module(record_id=f"REC-CNT-{i}"))

        assert service.count_modules("trusted") == 3
        assert service.count_modules("review") == 0


# ═══════════════════════════════════════════════════════════════════════
#  G. PROTOCOL COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════


class TestProtocolCompliance:
    """Verify fake satisfies the port protocol."""

    def test_fake_repo_satisfies_protocol(self) -> None:
        from fault_mapper.domain.ports import FaultModuleRepositoryPort
        repo = FakeFaultModuleRepository()
        assert isinstance(repo, FaultModuleRepositoryPort)
