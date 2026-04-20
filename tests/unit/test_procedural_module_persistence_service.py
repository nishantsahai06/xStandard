"""Tests for ``ProceduralModulePersistenceService``.

Covers:
  • Routing: APPROVED → procedural_trusted, NOT_REVIEWED → procedural_review
  • Rejection: REJECTED review_status
  • Envelope shape and metadata
  • Error handling: serialiser failure, repository failure
  • Multiple persist operations, upsert
  • Retrieve / list / count delegation
  • Protocol compliance
  • Factory integration

Mirrors ``test_fault_module_persistence_service.py`` structurally.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.application.procedural_module_persistence_service import (
    ProceduralModulePersistenceService,
)
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.procedural_persistence_fixtures import (
    make_approved_procedural_module,
    make_not_reviewed_procedural_module,
    make_rejected_procedural_module,
    make_procedural_envelope,
)


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_repo() -> FakeFaultModuleRepository:
    return FakeFaultModuleRepository()


@pytest.fixture
def service(fake_repo: FakeFaultModuleRepository) -> ProceduralModulePersistenceService:
    return ProceduralModulePersistenceService(repository=fake_repo)


# ═══════════════════════════════════════════════════════════════════════
#  A. ROUTING — APPROVED → PROCEDURAL_TRUSTED
# ═══════════════════════════════════════════════════════════════════════


class TestPersistApproved:
    """APPROVED modules route to the 'procedural_trusted' collection."""

    def test_approved_persists_to_procedural_trusted(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_procedural_module()
        result = service.persist(module)

        assert result.success is True
        assert result.collection == "procedural_trusted"
        assert result.record_id == module.record_id
        assert result.stored_at is not None
        assert len(fake_repo.save_calls) == 1
        assert fake_repo.save_calls[0].collection == "procedural_trusted"

    def test_envelope_carries_correct_metadata(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_procedural_module(mapping_version="2.0.0")
        service.persist(module)

        env = fake_repo.save_calls[0]
        assert env.mapping_version == "2.0.0"
        assert env.validation_status is ValidationStatus.APPROVED
        assert env.review_status is ReviewStatus.APPROVED
        assert env.stored_at is not None
        assert isinstance(env.document, dict)
        assert env.document["csdbRecordId"] == module.record_id

    def test_envelope_document_contains_serialised_module(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_procedural_module()
        service.persist(module)

        doc = fake_repo.save_calls[0].document
        assert "csdbRecordId" in doc
        assert "identAndStatusSection" in doc
        assert "content" in doc


# ═══════════════════════════════════════════════════════════════════════
#  B. ROUTING — NOT_REVIEWED → PROCEDURAL_REVIEW
# ═══════════════════════════════════════════════════════════════════════


class TestPersistNotReviewed:
    """NOT_REVIEWED modules route to the 'procedural_review' collection."""

    def test_not_reviewed_persists_to_procedural_review(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_not_reviewed_procedural_module()
        result = service.persist(module)

        assert result.success is True
        assert result.collection == "procedural_review"
        assert len(fake_repo.save_calls) == 1
        assert fake_repo.save_calls[0].collection == "procedural_review"

    def test_not_reviewed_envelope_metadata(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_not_reviewed_procedural_module()
        service.persist(module)

        env = fake_repo.save_calls[0]
        assert env.validation_status is ValidationStatus.REVIEW_REQUIRED
        assert env.review_status is ReviewStatus.NOT_REVIEWED


# ═══════════════════════════════════════════════════════════════════════
#  C. REJECTION — INELIGIBLE STATUSES
# ═══════════════════════════════════════════════════════════════════════


class TestPersistRejected:
    """Modules with non-persistable review_status are rejected."""

    def test_rejected_returns_failure(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_rejected_procedural_module()
        result = service.persist(module)

        assert result.success is False
        assert result.collection == ""
        assert "only APPROVED and NOT_REVIEWED" in (result.error or "")
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

        svc = ProceduralModulePersistenceService(
            repository=fake_repo,
            serializer=bad_serializer,
        )
        module = make_approved_procedural_module()
        result = svc.persist(module)

        assert result.success is False
        assert "Serialisation failed" in (result.error or "")
        assert result.collection == "procedural_trusted"

    def test_repository_failure_returns_error_result(
        self, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        fake_repo.fail_on_save = True
        svc = ProceduralModulePersistenceService(repository=fake_repo)

        module = make_approved_procedural_module()
        result = svc.persist(module)

        assert result.success is False
        assert "Simulated repository failure" in (result.error or "")

    def test_repository_exception_is_caught(self) -> None:
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

        svc = ProceduralModulePersistenceService(repository=ExplodingRepo())
        module = make_approved_procedural_module()
        result = svc.persist(module)

        assert result.success is False
        assert "Repository write failed" in (result.error or "")


# ═══════════════════════════════════════════════════════════════════════
#  E. MULTIPLE PERSIST OPERATIONS
# ═══════════════════════════════════════════════════════════════════════


class TestMultiplePersists:
    """Persisting multiple modules accumulates in the repository."""

    def test_two_approved_modules(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        m1 = make_approved_procedural_module(record_id="REC-A")
        m2 = make_approved_procedural_module(record_id="REC-B")
        r1 = service.persist(m1)
        r2 = service.persist(m2)

        assert r1.success and r2.success
        assert fake_repo.count("procedural_trusted") == 2

    def test_mixed_routing(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        approved = make_approved_procedural_module(record_id="REC-T")
        review = make_not_reviewed_procedural_module(record_id="REC-R")
        rejected = make_rejected_procedural_module(record_id="REC-X")

        service.persist(approved)
        service.persist(review)
        service.persist(rejected)

        assert fake_repo.count("procedural_trusted") == 1
        assert fake_repo.count("procedural_review") == 1
        assert len(fake_repo.save_calls) == 2  # rejected was not saved

    def test_upsert_replaces_existing(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        m1 = make_approved_procedural_module(record_id="REC-UPSERT")
        service.persist(m1)
        assert fake_repo.count("procedural_trusted") == 1

        # Re-persist same record_id — different version
        m2 = make_approved_procedural_module(
            record_id="REC-UPSERT",
            mapping_version="2.0.0",
        )
        service.persist(m2)

        # Still just 1 doc (upserted)
        assert fake_repo.count("procedural_trusted") == 1
        env = fake_repo.get("REC-UPSERT", "procedural_trusted")
        assert env is not None
        assert env.mapping_version == "2.0.0"


# ═══════════════════════════════════════════════════════════════════════
#  F. RETRIEVE / LIST / COUNT
# ═══════════════════════════════════════════════════════════════════════


class TestRetrieveAndList:
    """Service delegates read operations to the repository."""

    def test_retrieve_existing(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        module = make_approved_procedural_module(record_id="REC-GET")
        service.persist(module)

        env = service.retrieve("REC-GET", "procedural_trusted")
        assert env is not None
        assert env.record_id == "REC-GET"

    def test_retrieve_missing_returns_none(
        self, service: ProceduralModulePersistenceService,
    ) -> None:
        assert service.retrieve("NONEXISTENT", "procedural_trusted") is None

    def test_list_modules(
        self, service: ProceduralModulePersistenceService,
    ) -> None:
        for i in range(5):
            m = make_approved_procedural_module(record_id=f"REC-LIST-{i}")
            service.persist(m)

        result = service.list_modules("procedural_trusted", limit=3)
        assert len(result) == 3

    def test_count_modules(
        self, service: ProceduralModulePersistenceService,
    ) -> None:
        for i in range(3):
            service.persist(make_approved_procedural_module(record_id=f"REC-CNT-{i}"))

        assert service.count_modules("procedural_trusted") == 3
        assert service.count_modules("procedural_review") == 0

    def test_default_collection_is_procedural_trusted(
        self, service: ProceduralModulePersistenceService,
    ) -> None:
        module = make_approved_procedural_module(record_id="REC-DEFAULT")
        service.persist(module)

        # Default collection for retrieve/list/count
        env = service.retrieve("REC-DEFAULT")
        assert env is not None


# ═══════════════════════════════════════════════════════════════════════
#  G. PROTOCOL COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════


class TestProtocolCompliance:
    """Verify fake satisfies the shared port protocol."""

    def test_fake_repo_satisfies_protocol(self) -> None:
        from fault_mapper.domain.ports import FaultModuleRepositoryPort
        repo = FakeFaultModuleRepository()
        assert isinstance(repo, FaultModuleRepositoryPort)


# ═══════════════════════════════════════════════════════════════════════
#  H. FACTORY INTEGRATION
# ═══════════════════════════════════════════════════════════════════════


class TestFactoryIntegration:
    """ProceduralMapperFactory can create the persistence service."""

    def test_factory_creates_persistence_service(self) -> None:
        from fault_mapper.infrastructure.procedural_factory import (
            ProceduralMapperFactory,
        )
        from fault_mapper.infrastructure.procedural_config import (
            ProceduralAppConfig,
        )

        factory = ProceduralMapperFactory(
            config=ProceduralAppConfig(),
            llm_client=lambda: None,  # dummy
        )
        svc = factory.create_persistence_service()
        assert isinstance(svc, ProceduralModulePersistenceService)

    def test_factory_with_custom_repository(self) -> None:
        from fault_mapper.infrastructure.procedural_factory import (
            ProceduralMapperFactory,
        )
        from fault_mapper.infrastructure.procedural_config import (
            ProceduralAppConfig,
        )

        repo = FakeFaultModuleRepository()
        factory = ProceduralMapperFactory(
            config=ProceduralAppConfig(),
            llm_client=lambda: None,
            repository=repo,
        )
        svc = factory.create_persistence_service()

        module = make_approved_procedural_module()
        result = svc.persist(module)

        assert result.success is True
        assert len(repo.save_calls) == 1


# ═══════════════════════════════════════════════════════════════════════
#  I. COLLECTION NAMESPACE SEGREGATION
# ═══════════════════════════════════════════════════════════════════════


class TestCollectionSegregation:
    """Procedural and fault modules use different collection namespaces."""

    def test_procedural_collections_are_namespaced(
        self, service: ProceduralModulePersistenceService, fake_repo: FakeFaultModuleRepository,
    ) -> None:
        """Procedural modules use 'procedural_trusted'/'procedural_review',
        not 'trusted'/'review' (which are fault collections)."""
        approved = make_approved_procedural_module()
        review = make_not_reviewed_procedural_module()

        service.persist(approved)
        service.persist(review)

        # Procedural collections populated
        assert fake_repo.count("procedural_trusted") == 1
        assert fake_repo.count("procedural_review") == 1
        # Fault collections untouched
        assert fake_repo.count("trusted") == 0
        assert fake_repo.count("review") == 0
