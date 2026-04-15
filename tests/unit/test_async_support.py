"""Tests for Chunk-16 async support.

Covers:
  ═══════════════════════════════════════════════════════════════════
  A. ASYNC PERSISTENCE SERVICE  (8 tests)
  ═══════════════════════════════════════════════════════════════════
  1. persist approved module → trusted collection
  2. persist review-required module → review collection
  3. persist ineligible module → rejected
  4. retrieve stored module by record_id
  5. list_modules returns stored envelopes
  6. count_modules returns correct count
  7. repository failure propagated in PersistenceResult
  8. retrieve non-existent returns None

  ═══════════════════════════════════════════════════════════════════
  B. ASYNC REVIEW SERVICE  (10 tests)
  ═══════════════════════════════════════════════════════════════════
  9.  approve review item → moves to trusted
  10. approve missing item → not found error
  11. reject review item → stays in review with REJECTED status
  12. reject missing item → not found error
  13. get_review_item returns correct envelope
  14. get_review_item non-existent → None
  15. list_review_items returns all review items
  16. count_review_items returns count
  17. approve writes audit entry
  18. audit failure does NOT block approve

  ═══════════════════════════════════════════════════════════════════
  C. ASYNC RECONCILIATION SERVICE  (8 tests)
  ═══════════════════════════════════════════════════════════════════
  19. sweep with no duplicates → clean report
  20. sweep detects and cleans orphan
  21. sweep dry_run does not delete
  22. sweep skips non-authoritative trusted status
  23. sweep skips non-orphan review status
  24. find_orphaned_review_ids returns overlap
  25. sweep limit caps scan count
  26. sweep handles delete failure → error in report

  ═══════════════════════════════════════════════════════════════════
  D. ASYNC INSTRUMENTED WRAPPERS  (6 tests)
  ═══════════════════════════════════════════════════════════════════
  27. instrumented persistence emits metrics
  28. instrumented review approve emits metrics
  29. instrumented review reject emits metrics
  30. instrumented reconciliation sweep emits metrics
  31. instrumented persistence failure emits failure metric
  32. instrumented review not-found emits not_found metric

  ═══════════════════════════════════════════════════════════════════
  E. ASYNC API (AsyncServiceProvider) (6 tests)
  ═══════════════════════════════════════════════════════════════════
  33. async health endpoint
  34. async approve endpoint
  35. async reject endpoint
  36. async get_review_item endpoint
  37. async list_review_items endpoint
  38. async sweep endpoint

  ═══════════════════════════════════════════════════════════════════
  F. FACTORY ASYNC WIRING  (4 tests)
  ═══════════════════════════════════════════════════════════════════
  39. create_async_persistence_service returns correct type
  40. create_async_review_service returns correct type
  41. create_async_reconciliation_service returns correct type
  42. build_async_services returns AsyncServiceProvider
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.async_in_memory_audit_repository import (
    AsyncInMemoryAuditRepository,
)
from fault_mapper.adapters.secondary.async_in_memory_repository import (
    AsyncInMemoryFaultModuleRepository,
)
from fault_mapper.adapters.secondary.async_instrumented_services import (
    AsyncInstrumentedFaultModulePersistenceService,
    AsyncInstrumentedFaultModuleReviewService,
    AsyncInstrumentedFaultModuleReconciliationService,
)
from fault_mapper.adapters.secondary.in_memory_metrics_sink import (
    InMemoryMetricsSink,
)
from fault_mapper.application.async_persistence_service import (
    AsyncFaultModulePersistenceService,
)
from fault_mapper.application.async_reconciliation_service import (
    AsyncFaultModuleReconciliationService,
)
from fault_mapper.application.async_review_service import (
    AsyncFaultModuleReviewService,
)
from fault_mapper.domain.enums import (
    AuditEventType,
    ReconciliationOutcome,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.value_objects import PersistenceEnvelope

from tests.fakes.async_fake_audit_repository import AsyncFakeAuditRepository
from tests.fakes.async_fake_fault_module_repository import (
    AsyncFakeFaultModuleRepository,
)
from tests.fixtures.persistence_fixtures import (
    make_approved_module,
    make_envelope,
    make_review_required_module,
    make_schema_failed_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _review_envelope(
    record_id: str = "ASYNC-001",
    **overrides: object,
) -> PersistenceEnvelope:
    defaults = dict(
        record_id=record_id,
        collection="review",
        validation_status=ValidationStatus.REVIEW_REQUIRED,
        review_status=ReviewStatus.NOT_REVIEWED,
    )
    defaults.update(overrides)
    return make_envelope(**defaults)


def _trusted_envelope(
    record_id: str = "ASYNC-001",
    **overrides: object,
) -> PersistenceEnvelope:
    defaults = dict(
        record_id=record_id,
        collection="trusted",
        validation_status=ValidationStatus.APPROVED,
        review_status=ReviewStatus.APPROVED,
    )
    defaults.update(overrides)
    return make_envelope(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def repo() -> AsyncFakeFaultModuleRepository:
    return AsyncFakeFaultModuleRepository()


@pytest.fixture()
def audit_repo() -> AsyncFakeAuditRepository:
    return AsyncFakeAuditRepository()


@pytest.fixture()
def persistence_svc(
    repo: AsyncFakeFaultModuleRepository,
) -> AsyncFaultModulePersistenceService:
    return AsyncFaultModulePersistenceService(repository=repo)


@pytest.fixture()
def review_svc(
    repo: AsyncFakeFaultModuleRepository,
    audit_repo: AsyncFakeAuditRepository,
) -> AsyncFaultModuleReviewService:
    return AsyncFaultModuleReviewService(
        repository=repo, audit_repo=audit_repo,
    )


@pytest.fixture()
def reconciliation_svc(
    repo: AsyncFakeFaultModuleRepository,
    audit_repo: AsyncFakeAuditRepository,
) -> AsyncFaultModuleReconciliationService:
    return AsyncFaultModuleReconciliationService(
        repository=repo, audit_repo=audit_repo,
    )


@pytest.fixture()
def metrics() -> InMemoryMetricsSink:
    return InMemoryMetricsSink()


# ═══════════════════════════════════════════════════════════════════════
#  A. ASYNC PERSISTENCE SERVICE
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncPersistenceService:
    """Tests for ``AsyncFaultModulePersistenceService``."""

    @pytest.mark.asyncio
    async def test_persist_approved_module(
        self, persistence_svc: AsyncFaultModulePersistenceService,
    ) -> None:
        module = make_approved_module()
        result = await persistence_svc.persist(module)
        assert result.success is True
        assert result.collection == "trusted"

    @pytest.mark.asyncio
    async def test_persist_review_required_module(
        self, persistence_svc: AsyncFaultModulePersistenceService,
    ) -> None:
        module = make_review_required_module()
        result = await persistence_svc.persist(module)
        assert result.success is True
        assert result.collection == "review"

    @pytest.mark.asyncio
    async def test_persist_ineligible_module(
        self, persistence_svc: AsyncFaultModulePersistenceService,
    ) -> None:
        module = make_schema_failed_module()
        result = await persistence_svc.persist(module)
        assert result.success is False
        assert "schema_failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_retrieve_stored_module(
        self,
        repo: AsyncFakeFaultModuleRepository,
        persistence_svc: AsyncFaultModulePersistenceService,
    ) -> None:
        module = make_approved_module(record_id="REC-RET-001")
        await persistence_svc.persist(module)
        env = await persistence_svc.retrieve("REC-RET-001", "trusted")
        assert env is not None
        assert env.record_id == "REC-RET-001"

    @pytest.mark.asyncio
    async def test_list_modules(
        self, persistence_svc: AsyncFaultModulePersistenceService,
    ) -> None:
        m1 = make_approved_module(record_id="REC-LIST-A")
        m2 = make_approved_module(record_id="REC-LIST-B")
        await persistence_svc.persist(m1)
        await persistence_svc.persist(m2)
        envs = await persistence_svc.list_modules("trusted")
        assert len(envs) == 2

    @pytest.mark.asyncio
    async def test_count_modules(
        self, persistence_svc: AsyncFaultModulePersistenceService,
    ) -> None:
        m1 = make_approved_module(record_id="REC-CNT-A")
        await persistence_svc.persist(m1)
        count = await persistence_svc.count_modules("trusted")
        assert count == 1

    @pytest.mark.asyncio
    async def test_repository_failure(
        self,
        repo: AsyncFakeFaultModuleRepository,
        persistence_svc: AsyncFaultModulePersistenceService,
    ) -> None:
        repo.fail_on_save = True
        module = make_approved_module()
        result = await persistence_svc.persist(module)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent(
        self, persistence_svc: AsyncFaultModulePersistenceService,
    ) -> None:
        env = await persistence_svc.retrieve("NONEXISTENT", "trusted")
        assert env is None


# ═══════════════════════════════════════════════════════════════════════
#  B. ASYNC REVIEW SERVICE
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncReviewService:
    """Tests for ``AsyncFaultModuleReviewService``."""

    @pytest.mark.asyncio
    async def test_approve_review_item(
        self,
        repo: AsyncFakeFaultModuleRepository,
        review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        env = _review_envelope(record_id="REV-APP-001")
        await repo.save(env)
        result = await review_svc.approve("REV-APP-001")
        assert result.success is True
        assert result.collection == "trusted"
        # Verify moved to trusted
        trusted = await repo.get("REV-APP-001", "trusted")
        assert trusted is not None
        # Verify removed from review
        review = await repo.get("REV-APP-001", "review")
        assert review is None

    @pytest.mark.asyncio
    async def test_approve_missing_item(
        self, review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        result = await review_svc.approve("NOPE")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_reject_review_item(
        self,
        repo: AsyncFakeFaultModuleRepository,
        review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        env = _review_envelope(record_id="REV-REJ-001")
        await repo.save(env)
        result = await review_svc.reject("REV-REJ-001", "Bad data")
        assert result.success is True
        # Still in review but now REJECTED
        rejected = await repo.get("REV-REJ-001", "review")
        assert rejected is not None
        assert rejected.validation_status == ValidationStatus.REJECTED

    @pytest.mark.asyncio
    async def test_reject_missing_item(
        self, review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        result = await review_svc.reject("NOPE", "reason")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_review_item(
        self,
        repo: AsyncFakeFaultModuleRepository,
        review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        env = _review_envelope(record_id="REV-GET-001")
        await repo.save(env)
        fetched = await review_svc.get_review_item("REV-GET-001")
        assert fetched is not None
        assert fetched.record_id == "REV-GET-001"

    @pytest.mark.asyncio
    async def test_get_review_item_nonexistent(
        self, review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        fetched = await review_svc.get_review_item("NOPE")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_list_review_items(
        self,
        repo: AsyncFakeFaultModuleRepository,
        review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        for i in range(3):
            await repo.save(_review_envelope(record_id=f"REV-LIST-{i}"))
        items = await review_svc.list_review_items()
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_count_review_items(
        self,
        repo: AsyncFakeFaultModuleRepository,
        review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        await repo.save(_review_envelope(record_id="REV-CNT-A"))
        await repo.save(_review_envelope(record_id="REV-CNT-B"))
        count = await review_svc.count_review_items()
        assert count == 2

    @pytest.mark.asyncio
    async def test_approve_writes_audit_entry(
        self,
        repo: AsyncFakeFaultModuleRepository,
        audit_repo: AsyncFakeAuditRepository,
        review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        await repo.save(_review_envelope(record_id="REV-AUD-001"))
        await review_svc.approve("REV-AUD-001", reason="Looks good")
        assert len(audit_repo.append_calls) == 1
        entry = audit_repo.append_calls[0]
        assert entry.event_type == AuditEventType.REVIEW_APPROVED
        assert entry.record_id == "REV-AUD-001"

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_block_approve(
        self,
        repo: AsyncFakeFaultModuleRepository,
        audit_repo: AsyncFakeAuditRepository,
        review_svc: AsyncFaultModuleReviewService,
    ) -> None:
        audit_repo.fail_on_append = True
        await repo.save(_review_envelope(record_id="REV-AUD-FAIL"))
        result = await review_svc.approve("REV-AUD-FAIL")
        assert result.success is True  # Not blocked by audit failure


# ═══════════════════════════════════════════════════════════════════════
#  C. ASYNC RECONCILIATION SERVICE
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncReconciliationService:
    """Tests for ``AsyncFaultModuleReconciliationService``."""

    @pytest.mark.asyncio
    async def test_sweep_no_duplicates(
        self,
        repo: AsyncFakeFaultModuleRepository,
        reconciliation_svc: AsyncFaultModuleReconciliationService,
    ) -> None:
        await repo.save(_review_envelope(record_id="REC-ONLY"))
        report = await reconciliation_svc.sweep()
        assert report.total_review_scanned == 1
        assert report.duplicates_found == 0
        assert report.duplicates_cleaned == 0

    @pytest.mark.asyncio
    async def test_sweep_cleans_orphan(
        self,
        repo: AsyncFakeFaultModuleRepository,
        reconciliation_svc: AsyncFaultModuleReconciliationService,
    ) -> None:
        # Create a valid orphan: same ID in both, review has APPROVED status
        await repo.save(_trusted_envelope(record_id="ORPHAN-001"))
        await repo.save(
            _review_envelope(
                record_id="ORPHAN-001",
                validation_status=ValidationStatus.APPROVED,
                review_status=ReviewStatus.APPROVED,
            ),
        )
        report = await reconciliation_svc.sweep()
        assert report.duplicates_found == 1
        assert report.duplicates_cleaned == 1
        # Review entry should be gone
        review = await repo.get("ORPHAN-001", "review")
        assert review is None

    @pytest.mark.asyncio
    async def test_sweep_dry_run_no_delete(
        self,
        repo: AsyncFakeFaultModuleRepository,
        reconciliation_svc: AsyncFaultModuleReconciliationService,
    ) -> None:
        await repo.save(_trusted_envelope(record_id="DRY-001"))
        await repo.save(
            _review_envelope(
                record_id="DRY-001",
                validation_status=ValidationStatus.APPROVED,
                review_status=ReviewStatus.APPROVED,
            ),
        )
        report = await reconciliation_svc.sweep(dry_run=True)
        assert report.duplicates_cleaned == 1
        assert report.dry_run is True
        # Review entry should still exist
        review = await repo.get("DRY-001", "review")
        assert review is not None

    @pytest.mark.asyncio
    async def test_sweep_skips_non_authoritative_trusted(
        self,
        repo: AsyncFakeFaultModuleRepository,
        reconciliation_svc: AsyncFaultModuleReconciliationService,
    ) -> None:
        # Trusted record with non-authoritative status → skip
        await repo.save(
            _trusted_envelope(
                record_id="SKIP-001",
                validation_status=ValidationStatus.REVIEW_REQUIRED,
            ),
        )
        await repo.save(
            _review_envelope(
                record_id="SKIP-001",
                validation_status=ValidationStatus.APPROVED,
            ),
        )
        report = await reconciliation_svc.sweep()
        assert report.duplicates_skipped == 1
        assert report.duplicates_cleaned == 0

    @pytest.mark.asyncio
    async def test_sweep_skips_non_orphan_review(
        self,
        repo: AsyncFakeFaultModuleRepository,
        reconciliation_svc: AsyncFaultModuleReconciliationService,
    ) -> None:
        # Review record with REVIEW_REQUIRED (not APPROVED) → skip
        await repo.save(_trusted_envelope(record_id="SKIP-002"))
        await repo.save(_review_envelope(record_id="SKIP-002"))
        report = await reconciliation_svc.sweep()
        assert report.duplicates_skipped == 1
        assert report.duplicates_cleaned == 0

    @pytest.mark.asyncio
    async def test_find_orphaned_review_ids(
        self,
        repo: AsyncFakeFaultModuleRepository,
        reconciliation_svc: AsyncFaultModuleReconciliationService,
    ) -> None:
        await repo.save(_trusted_envelope(record_id="BOTH-001"))
        await repo.save(_review_envelope(record_id="BOTH-001"))
        await repo.save(_review_envelope(record_id="ONLY-REVIEW"))
        ids = await reconciliation_svc.find_orphaned_review_ids()
        assert ids == ["BOTH-001"]

    @pytest.mark.asyncio
    async def test_sweep_limit(
        self,
        repo: AsyncFakeFaultModuleRepository,
        reconciliation_svc: AsyncFaultModuleReconciliationService,
    ) -> None:
        for i in range(5):
            await repo.save(_review_envelope(record_id=f"LIM-{i}"))
        report = await reconciliation_svc.sweep(limit=2)
        assert report.total_review_scanned == 2

    @pytest.mark.asyncio
    async def test_sweep_delete_failure_error(
        self,
        repo: AsyncFakeFaultModuleRepository,
        reconciliation_svc: AsyncFaultModuleReconciliationService,
    ) -> None:
        await repo.save(_trusted_envelope(record_id="ERR-001"))
        await repo.save(
            _review_envelope(
                record_id="ERR-001",
                validation_status=ValidationStatus.APPROVED,
                review_status=ReviewStatus.APPROVED,
            ),
        )
        repo.fail_on_delete = True
        report = await reconciliation_svc.sweep()
        assert report.errors == 1
        assert report.duplicates_cleaned == 0


# ═══════════════════════════════════════════════════════════════════════
#  D. ASYNC INSTRUMENTED WRAPPERS
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncInstrumentedWrappers:
    """Tests for async instrumented service wrappers."""

    @pytest.mark.asyncio
    async def test_instrumented_persistence_emits_metrics(
        self,
        repo: AsyncFakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = AsyncFaultModulePersistenceService(repository=repo)
        svc = AsyncInstrumentedFaultModulePersistenceService(
            inner=inner, metrics=metrics,
        )
        module = make_approved_module()
        result = await svc.persist(module)
        assert result.success is True
        assert len(metrics.get("persistence.persist.executed")) == 1
        assert len(metrics.get("persistence.persist.success")) == 1

    @pytest.mark.asyncio
    async def test_instrumented_review_approve_emits_metrics(
        self,
        repo: AsyncFakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = AsyncFaultModuleReviewService(repository=repo)
        svc = AsyncInstrumentedFaultModuleReviewService(
            inner=inner, metrics=metrics,
        )
        await repo.save(_review_envelope(record_id="INST-APP-001"))
        result = await svc.approve("INST-APP-001")
        assert result.success is True
        assert len(metrics.get("review.approve.executed")) == 1
        assert len(metrics.get("review.approve.success")) == 1

    @pytest.mark.asyncio
    async def test_instrumented_review_reject_emits_metrics(
        self,
        repo: AsyncFakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = AsyncFaultModuleReviewService(repository=repo)
        svc = AsyncInstrumentedFaultModuleReviewService(
            inner=inner, metrics=metrics,
        )
        await repo.save(_review_envelope(record_id="INST-REJ-001"))
        result = await svc.reject("INST-REJ-001", "Bad data")
        assert result.success is True
        assert len(metrics.get("review.reject.executed")) == 1
        assert len(metrics.get("review.reject.success")) == 1

    @pytest.mark.asyncio
    async def test_instrumented_reconciliation_emits_metrics(
        self,
        repo: AsyncFakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = AsyncFaultModuleReconciliationService(repository=repo)
        svc = AsyncInstrumentedFaultModuleReconciliationService(
            inner=inner, metrics=metrics,
        )
        report = await svc.sweep()
        assert report.total_review_scanned == 0
        assert len(metrics.get("reconciliation.sweep.executed")) == 1

    @pytest.mark.asyncio
    async def test_instrumented_persistence_failure_metric(
        self,
        repo: AsyncFakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        repo.fail_on_save = True
        inner = AsyncFaultModulePersistenceService(repository=repo)
        svc = AsyncInstrumentedFaultModulePersistenceService(
            inner=inner, metrics=metrics,
        )
        module = make_approved_module()
        result = await svc.persist(module)
        assert result.success is False
        assert len(metrics.get("persistence.persist.failure")) == 1

    @pytest.mark.asyncio
    async def test_instrumented_review_not_found_metric(
        self,
        repo: AsyncFakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = AsyncFaultModuleReviewService(repository=repo)
        svc = AsyncInstrumentedFaultModuleReviewService(
            inner=inner, metrics=metrics,
        )
        result = await svc.approve("NONEXISTENT")
        assert result.success is False
        assert len(metrics.get("review.not_found")) == 1


# ═══════════════════════════════════════════════════════════════════════
#  E. ASYNC API (via AsyncServiceProvider)
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncAPI:
    """Tests for API routes using ``AsyncServiceProvider``."""

    @pytest.fixture()
    def async_provider(
        self,
        repo: AsyncFakeFaultModuleRepository,
        audit_repo: AsyncFakeAuditRepository,
    ):
        from fault_mapper.adapters.primary.api.dependencies import (
            AsyncServiceProvider,
        )

        return AsyncServiceProvider(
            use_case=None,
            persistence=AsyncFaultModulePersistenceService(repository=repo),
            review=AsyncFaultModuleReviewService(
                repository=repo, audit_repo=audit_repo,
            ),
            reconciliation=AsyncFaultModuleReconciliationService(
                repository=repo, audit_repo=audit_repo,
            ),
        )

    @pytest.fixture()
    def client(self, async_provider):
        from fastapi.testclient import TestClient

        from fault_mapper.adapters.primary.api.app import create_app

        app = create_app(async_provider)
        return TestClient(app)

    def test_async_health(self, client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_async_approve(
        self,
        repo: AsyncFakeFaultModuleRepository,
        client,
    ) -> None:
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.save(_review_envelope(record_id="API-APP-001")),
        )
        resp = client.post("/review/API-APP-001/approve")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_async_reject(
        self,
        repo: AsyncFakeFaultModuleRepository,
        client,
    ) -> None:
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.save(_review_envelope(record_id="API-REJ-001")),
        )
        resp = client.post(
            "/review/API-REJ-001/reject",
            json={"reason": "Bad", "performed_by": "tester"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_async_get_review_item_not_found(self, client) -> None:
        resp = client.get("/review/NOPE")
        assert resp.status_code == 404

    def test_async_list_review_items(
        self,
        repo: AsyncFakeFaultModuleRepository,
        client,
    ) -> None:
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.save(_review_envelope(record_id="API-LIST-001")),
        )
        resp = client.get("/review")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["items"]) == 1

    def test_async_sweep(self, client) -> None:
        resp = client.post("/reconciliation/sweep")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_review_scanned"] == 0


# ═══════════════════════════════════════════════════════════════════════
#  F. FACTORY ASYNC WIRING
# ═══════════════════════════════════════════════════════════════════════


class TestFactoryAsyncWiring:
    """Tests for async factory methods and ``build_async_services``."""

    def test_create_async_persistence_service(self) -> None:
        from fault_mapper.infrastructure.config import AppConfig
        from fault_mapper.infrastructure.factory import FaultMapperFactory

        factory = FaultMapperFactory(config=AppConfig())
        svc = factory.create_async_persistence_service()
        assert isinstance(svc, AsyncFaultModulePersistenceService)

    def test_create_async_review_service(self) -> None:
        from fault_mapper.infrastructure.config import AppConfig
        from fault_mapper.infrastructure.factory import FaultMapperFactory

        factory = FaultMapperFactory(config=AppConfig())
        svc = factory.create_async_review_service()
        assert isinstance(svc, AsyncFaultModuleReviewService)

    def test_create_async_reconciliation_service(self) -> None:
        from fault_mapper.infrastructure.config import AppConfig
        from fault_mapper.infrastructure.factory import FaultMapperFactory

        factory = FaultMapperFactory(config=AppConfig())
        svc = factory.create_async_reconciliation_service()
        assert isinstance(svc, AsyncFaultModuleReconciliationService)

    def test_build_async_services(self) -> None:
        from fault_mapper.adapters.primary.api.dependencies import (
            AsyncServiceProvider,
            build_async_services,
        )

        provider = build_async_services()
        assert isinstance(provider, AsyncServiceProvider)
        assert provider.use_case is None  # No LLM client
