"""Tests for Chunk 9 — procedural async/batch processing support.

Covers:
  ═══════════════════════════════════════════════════════════════════
  A. SYNC BATCH SERVICE  (10 tests)
  B. ASYNC BATCH SERVICE  (10 tests)
  C. INSTRUMENTED BATCH WRAPPERS  (6 tests)
  D. FACTORY WIRING  (4 tests)
  E. SERVICE PROVIDER  (2 tests)
  F. BATCH API ENDPOINT  (8 tests)
  G. BATCH CLI COMMAND  (6 tests)
  H. ASYNC PERSISTENCE  (4 tests)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fault_mapper.adapters.primary.api.app import create_app
from fault_mapper.adapters.primary.api.procedural_dependencies import (
    ProceduralServiceProvider,
    build_procedural_services,
)
from fault_mapper.adapters.primary.cli.procedural_main import (
    procedural_cli,
    set_procedural_services as cli_set_services,
)
from fault_mapper.adapters.secondary.async_in_memory_repository import (
    AsyncInMemoryFaultModuleRepository,
)
from fault_mapper.adapters.secondary.in_memory_metrics_sink import (
    InMemoryMetricsSink,
)
from fault_mapper.adapters.secondary.procedural_instrumented_services import (
    AsyncInstrumentedProceduralBatchProcessingService,
    InstrumentedProceduralBatchProcessingService,
)
from fault_mapper.application.async_procedural_batch_processing_service import (
    AsyncProceduralBatchProcessingService,
)
from fault_mapper.application.async_procedural_module_persistence_service import (
    AsyncProceduralModulePersistenceService,
)
from fault_mapper.application.procedural_batch_processing_service import (
    ProceduralBatchProcessingService,
)
from fault_mapper.application.procedural_module_persistence_service import (
    ProceduralModulePersistenceService,
)
from fault_mapper.domain.enums import ReviewStatus
from fault_mapper.domain.models import (
    DocumentPipelineOutput,
    Metadata,
    Section,
)
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.domain.value_objects import BatchItemResult, BatchReport
from tests.fakes.async_fake_fault_module_repository import (
    AsyncFakeFaultModuleRepository,
)
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS & STUBS
# ═══════════════════════════════════════════════════════════════════════


def _make_source(doc_id: str = "doc-001") -> DocumentPipelineOutput:
    """Minimal valid ``DocumentPipelineOutput``."""
    return DocumentPipelineOutput(
        id=doc_id,
        full_text="Procedural maintenance content.",
        file_name="test.pdf",
        file_type="pdf",
        source_path="/uploads/test.pdf",
        metadata=Metadata(),
        sections=[
            Section(
                section_title="Maintenance Steps",
                section_order=0,
                section_type="general",
                section_text="Step-by-step procedure data.",
                level=1,
            ),
        ],
        schematics=[],
    )


class _StubUseCase:
    """Fake procedural mapping use case."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        fail_ids: set[str] | None = None,
        review_status: ReviewStatus = ReviewStatus.APPROVED,
    ) -> None:
        self._should_fail = should_fail
        self._fail_ids = fail_ids or set()
        self._review_status = review_status
        self.execute_calls: list[str] = []

    def execute(self, source: DocumentPipelineOutput, **kwargs) -> S1000DProceduralDataModule:
        self.execute_calls.append(source.id)
        if self._should_fail or source.id in self._fail_ids:
            raise ValueError(f"No procedural-relevant sections in {source.id}")
        return S1000DProceduralDataModule(
            record_id=f"REC-{source.id}",
            review_status=self._review_status,
            mapping_version="1.0.0",
        )


class _FailingPersistenceStub:
    """Persistence stub that always raises."""

    def persist(self, module: Any) -> None:
        raise RuntimeError("DB down")


class _AsyncFailingPersistenceStub:
    """Async persistence stub that always raises."""

    async def persist(self, module: Any) -> None:
        raise RuntimeError("DB down")


# ═══════════════════════════════════════════════════════════════════════
#  A. SYNC BATCH SERVICE
# ═══════════════════════════════════════════════════════════════════════


class TestSyncProceduralBatchService:
    """Sync ``ProceduralBatchProcessingService`` tests."""

    def _build(
        self,
        use_case: _StubUseCase | None = None,
        repo: FakeFaultModuleRepository | None = None,
    ) -> tuple[ProceduralBatchProcessingService, FakeFaultModuleRepository]:
        repo = repo or FakeFaultModuleRepository()
        uc = use_case or _StubUseCase()
        persistence = ProceduralModulePersistenceService(repository=repo)
        svc = ProceduralBatchProcessingService(use_case=uc, persistence=persistence)
        return svc, repo

    # 1
    def test_all_items_succeed_aggregate_counts(self) -> None:
        svc, _ = self._build()
        items = [_make_source(f"doc-{i}") for i in range(3)]
        report = svc.process_batch(items)

        assert report.total == 3
        assert report.succeeded == 3
        assert report.failed == 0
        assert report.persisted_trusted == 3
        assert report.persisted_review == 0
        assert report.not_persisted == 0

    # 2
    def test_all_items_succeed_per_item_shape(self) -> None:
        svc, _ = self._build()
        items = [_make_source("doc-A"), _make_source("doc-B")]
        report = svc.process_batch(items)

        assert len(report.items) == 2
        for r in report.items:
            assert r.success is True
            assert r.record_id is not None
            assert r.collection == "procedural_trusted"
            assert r.persisted is True
            assert r.error is None

    # 3
    def test_partial_failure_mapping(self) -> None:
        uc = _StubUseCase(fail_ids={"doc-1"})
        svc, _ = self._build(use_case=uc)
        items = [_make_source("doc-0"), _make_source("doc-1"), _make_source("doc-2")]
        report = svc.process_batch(items)

        assert report.total == 3
        assert report.succeeded == 2
        assert report.failed == 1
        failed = [r for r in report.items if not r.success]
        assert len(failed) == 1
        assert failed[0].source_id == "doc-1"
        assert "Mapping failed" in (failed[0].error or "")

    # 4
    def test_all_items_fail_mapping(self) -> None:
        uc = _StubUseCase(should_fail=True)
        svc, _ = self._build(use_case=uc)
        items = [_make_source(f"doc-{i}") for i in range(2)]
        report = svc.process_batch(items)

        assert report.total == 2
        assert report.succeeded == 0
        assert report.failed == 2

    # 5
    def test_persistence_failure_isolated(self) -> None:
        uc = _StubUseCase()
        svc = ProceduralBatchProcessingService(
            use_case=uc,
            persistence=_FailingPersistenceStub(),  # type: ignore[arg-type]
        )
        report = svc.process_batch([_make_source("doc-0")])

        assert report.total == 1
        assert report.failed == 1
        assert report.items[0].success is False
        assert "Persistence failed" in (report.items[0].error or "")
        assert report.items[0].record_id == "REC-doc-0"

    # 6
    def test_empty_batch(self) -> None:
        svc, _ = self._build()
        report = svc.process_batch([])

        assert report.total == 0
        assert report.succeeded == 0
        assert report.failed == 0
        assert report.items == []

    # 7
    def test_single_item_succeeds(self) -> None:
        svc, _ = self._build()
        report = svc.process_batch([_make_source("doc-only")])

        assert report.total == 1
        assert report.succeeded == 1
        assert report.items[0].source_id == "doc-only"

    # 8
    def test_review_required_module_persisted_review_count(self) -> None:
        uc = _StubUseCase(review_status=ReviewStatus.NOT_REVIEWED)
        svc, _ = self._build(use_case=uc)
        report = svc.process_batch([_make_source("doc-r")])

        assert report.persisted_review == 1
        assert report.persisted_trusted == 0
        assert report.items[0].collection == "procedural_review"

    # 9
    def test_rejected_module_not_persisted(self) -> None:
        uc = _StubUseCase(review_status=ReviewStatus.REJECTED)
        svc, _ = self._build(use_case=uc)
        report = svc.process_batch([_make_source("doc-rej")])

        assert report.not_persisted >= 1

    # 10
    def test_elapsed_ms_positive(self) -> None:
        svc, _ = self._build()
        report = svc.process_batch([_make_source("doc-t")])
        assert report.elapsed_ms >= 0


# ═══════════════════════════════════════════════════════════════════════
#  B. ASYNC BATCH SERVICE
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncProceduralBatchService:
    """Async ``AsyncProceduralBatchProcessingService`` tests."""

    def _build(
        self,
        use_case: _StubUseCase | None = None,
        repo: AsyncFakeFaultModuleRepository | None = None,
        max_concurrency: int = 5,
    ) -> tuple[AsyncProceduralBatchProcessingService, AsyncFakeFaultModuleRepository]:
        repo = repo or AsyncFakeFaultModuleRepository()
        uc = use_case or _StubUseCase()
        persistence = AsyncProceduralModulePersistenceService(repository=repo)
        svc = AsyncProceduralBatchProcessingService(
            use_case=uc, persistence=persistence, max_concurrency=max_concurrency,
        )
        return svc, repo

    # 11
    @pytest.mark.asyncio(loop_scope="function")
    async def test_all_items_succeed_aggregate(self) -> None:
        svc, _ = self._build()
        items = [_make_source(f"doc-{i}") for i in range(3)]
        report = await svc.process_batch(items)

        assert report.total == 3
        assert report.succeeded == 3
        assert report.failed == 0
        assert report.persisted_trusted == 3

    # 12
    @pytest.mark.asyncio(loop_scope="function")
    async def test_per_item_results_match(self) -> None:
        svc, _ = self._build()
        items = [_make_source("a"), _make_source("b")]
        report = await svc.process_batch(items)

        ids = {r.source_id for r in report.items}
        assert ids == {"a", "b"}

    # 13
    @pytest.mark.asyncio(loop_scope="function")
    async def test_partial_failure(self) -> None:
        uc = _StubUseCase(fail_ids={"doc-1"})
        svc, _ = self._build(use_case=uc)
        items = [_make_source("doc-0"), _make_source("doc-1"), _make_source("doc-2")]
        report = await svc.process_batch(items)

        assert report.succeeded == 2
        assert report.failed == 1

    # 14
    @pytest.mark.asyncio(loop_scope="function")
    async def test_all_fail(self) -> None:
        uc = _StubUseCase(should_fail=True)
        svc, _ = self._build(use_case=uc)
        report = await svc.process_batch([_make_source("x"), _make_source("y")])

        assert report.succeeded == 0
        assert report.failed == 2

    # 15
    @pytest.mark.asyncio(loop_scope="function")
    async def test_persistence_failure_isolated(self) -> None:
        uc = _StubUseCase()
        svc = AsyncProceduralBatchProcessingService(
            use_case=uc,
            persistence=_AsyncFailingPersistenceStub(),
            max_concurrency=2,
        )
        report = await svc.process_batch([_make_source("doc-0")])

        assert report.failed == 1
        assert report.items[0].record_id == "REC-doc-0"
        assert "Persistence failed" in (report.items[0].error or "")

    # 16
    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_batch(self) -> None:
        svc, _ = self._build()
        report = await svc.process_batch([])

        assert report.total == 0
        assert report.items == []

    # 17
    @pytest.mark.asyncio(loop_scope="function")
    async def test_single_item(self) -> None:
        svc, _ = self._build()
        report = await svc.process_batch([_make_source("only")])

        assert report.total == 1
        assert report.succeeded == 1

    # 18
    @pytest.mark.asyncio(loop_scope="function")
    async def test_review_required_count(self) -> None:
        uc = _StubUseCase(review_status=ReviewStatus.NOT_REVIEWED)
        svc, _ = self._build(use_case=uc)
        report = await svc.process_batch([_make_source("rev")])

        assert report.persisted_review == 1
        assert report.persisted_trusted == 0

    # 19
    @pytest.mark.asyncio(loop_scope="function")
    async def test_concurrency_bounded(self) -> None:
        """Verify that max_concurrency limits parallel execution."""

        class _TrackingUseCase:
            def execute(self, source: DocumentPipelineOutput, **kwargs) -> S1000DProceduralDataModule:
                return S1000DProceduralDataModule(
                    record_id=f"REC-{source.id}",
                    review_status=ReviewStatus.APPROVED,
                    mapping_version="1.0.0",
                )

        repo = AsyncFakeFaultModuleRepository()
        persistence = AsyncProceduralModulePersistenceService(repository=repo)
        svc = AsyncProceduralBatchProcessingService(
            use_case=_TrackingUseCase(),  # type: ignore[arg-type]
            persistence=persistence,
            max_concurrency=2,
        )
        items = [_make_source(f"doc-{i}") for i in range(5)]
        report = await svc.process_batch(items)

        assert report.total == 5
        assert report.succeeded == 5

    # 20
    @pytest.mark.asyncio(loop_scope="function")
    async def test_elapsed_ms_positive(self) -> None:
        svc, _ = self._build()
        report = await svc.process_batch([_make_source("t")])
        assert report.elapsed_ms >= 0


# ═══════════════════════════════════════════════════════════════════════
#  C. INSTRUMENTED BATCH WRAPPERS
# ═══════════════════════════════════════════════════════════════════════


class TestInstrumentedProceduralBatchSync:
    """Sync ``InstrumentedProceduralBatchProcessingService`` tests."""

    def _build(self) -> tuple[InstrumentedProceduralBatchProcessingService, InMemoryMetricsSink]:
        repo = FakeFaultModuleRepository()
        uc = _StubUseCase()
        inner = ProceduralBatchProcessingService(
            use_case=uc,
            persistence=ProceduralModulePersistenceService(repository=repo),
        )
        metrics = InMemoryMetricsSink()
        return InstrumentedProceduralBatchProcessingService(inner=inner, metrics=metrics), metrics

    # 21
    def test_emits_batch_executed(self) -> None:
        svc, metrics = self._build()
        svc.process_batch([_make_source("x")])
        hits = metrics.get("procedural.batch.executed", kind="increment")
        assert len(hits) >= 1

    # 22
    def test_emits_batch_duration_ms(self) -> None:
        svc, metrics = self._build()
        svc.process_batch([_make_source("x")])
        hits = metrics.get("procedural.batch.duration_ms", kind="timing")
        assert len(hits) == 1
        assert hits[0].value >= 0

    # 23
    def test_emits_succeeded_failed_gauges(self) -> None:
        svc, metrics = self._build()
        svc.process_batch([_make_source("a"), _make_source("b")])
        total = metrics.get("procedural.batch.total", kind="gauge")
        succeeded = metrics.get("procedural.batch.succeeded", kind="gauge")
        failed = metrics.get("procedural.batch.failed", kind="gauge")
        assert len(total) == 1 and total[0].value == 2
        assert len(succeeded) == 1 and succeeded[0].value == 2
        assert len(failed) == 1 and failed[0].value == 0


class TestInstrumentedProceduralBatchAsync:
    """Async ``AsyncInstrumentedProceduralBatchProcessingService`` tests."""

    def _build(self) -> tuple[AsyncInstrumentedProceduralBatchProcessingService, InMemoryMetricsSink]:
        repo = AsyncFakeFaultModuleRepository()
        uc = _StubUseCase()
        inner = AsyncProceduralBatchProcessingService(
            use_case=uc,
            persistence=AsyncProceduralModulePersistenceService(repository=repo),
        )
        metrics = InMemoryMetricsSink()
        return AsyncInstrumentedProceduralBatchProcessingService(inner=inner, metrics=metrics), metrics

    # 24
    @pytest.mark.asyncio(loop_scope="function")
    async def test_emits_batch_executed(self) -> None:
        svc, metrics = self._build()
        await svc.process_batch([_make_source("x")])
        hits = metrics.get("procedural.batch.executed", kind="increment")
        assert len(hits) >= 1

    # 25
    @pytest.mark.asyncio(loop_scope="function")
    async def test_emits_batch_duration_ms(self) -> None:
        svc, metrics = self._build()
        await svc.process_batch([_make_source("x")])
        hits = metrics.get("procedural.batch.duration_ms", kind="timing")
        assert len(hits) == 1
        assert hits[0].value >= 0

    # 26
    @pytest.mark.asyncio(loop_scope="function")
    async def test_emits_succeeded_failed_gauges(self) -> None:
        svc, metrics = self._build()
        await svc.process_batch([_make_source("a"), _make_source("b")])
        total = metrics.get("procedural.batch.total", kind="gauge")
        succeeded = metrics.get("procedural.batch.succeeded", kind="gauge")
        failed = metrics.get("procedural.batch.failed", kind="gauge")
        assert len(total) == 1 and total[0].value == 2
        assert len(succeeded) == 1 and succeeded[0].value == 2
        assert len(failed) == 1 and failed[0].value == 0


# ═══════════════════════════════════════════════════════════════════════
#  D. FACTORY WIRING
# ═══════════════════════════════════════════════════════════════════════


class TestProceduralFactoryBatchWiring:
    """Factory ``create_batch_*`` methods."""

    def _factory(
        self,
        metrics: InMemoryMetricsSink | None = None,
    ):
        from fault_mapper.infrastructure.procedural_factory import (
            ProceduralMapperFactory,
        )
        from fault_mapper.infrastructure.procedural_config import (
            ProceduralAppConfig,
        )
        return ProceduralMapperFactory(
            config=ProceduralAppConfig(),
            llm_client=lambda prompt: "stub-response",
        )

    # 27
    def test_create_batch_processing_service(self) -> None:
        factory = self._factory()
        svc = factory.create_batch_processing_service()
        assert isinstance(svc, ProceduralBatchProcessingService)

    # 28
    def test_create_batch_processing_service_instrumented(self) -> None:
        factory = self._factory()
        svc = factory.create_batch_processing_service(
            metrics_sink=InMemoryMetricsSink(),
        )
        assert isinstance(svc, InstrumentedProceduralBatchProcessingService)

    # 29
    def test_create_async_batch_processing_service(self) -> None:
        factory = self._factory()
        svc = factory.create_async_batch_processing_service()
        assert isinstance(svc, AsyncProceduralBatchProcessingService)

    # 30
    def test_create_async_batch_processing_service_instrumented(self) -> None:
        factory = self._factory()
        svc = factory.create_async_batch_processing_service(
            metrics_sink=InMemoryMetricsSink(),
        )
        assert isinstance(svc, AsyncInstrumentedProceduralBatchProcessingService)


# ═══════════════════════════════════════════════════════════════════════
#  E. SERVICE PROVIDER
# ═══════════════════════════════════════════════════════════════════════


class TestProceduralServiceProviderBatch:
    """Service provider batch field wiring."""

    # 31
    def test_build_services_with_llm_has_batch(self) -> None:
        sp = build_procedural_services(llm_client=lambda p: "stub")
        assert sp.batch is not None

    # 32
    def test_build_services_without_llm_no_batch(self) -> None:
        sp = build_procedural_services()
        assert sp.batch is None


# ═══════════════════════════════════════════════════════════════════════
#  F. BATCH API ENDPOINT
# ═══════════════════════════════════════════════════════════════════════


def _build_procedural_api_client(
    use_case: _StubUseCase | None = None,
    repo: FakeFaultModuleRepository | None = None,
    *,
    include_batch: bool = True,
) -> TestClient:
    """Build a TestClient with a ProceduralServiceProvider."""
    repo = repo or FakeFaultModuleRepository()
    uc = use_case or _StubUseCase()
    persistence = ProceduralModulePersistenceService(repository=repo)

    batch = None
    if include_batch:
        batch = ProceduralBatchProcessingService(use_case=uc, persistence=persistence)

    from fault_mapper.adapters.primary.api.dependencies import (
        ServiceProvider,
        build_services,
    )
    from fault_mapper.application.fault_module_persistence_service import (
        FaultModulePersistenceService,
    )
    from fault_mapper.application.fault_module_review_service import (
        FaultModuleReviewService,
    )
    from fault_mapper.application.fault_module_reconciliation_service import (
        FaultModuleReconciliationService,
    )

    fault_repo = FakeFaultModuleRepository()
    fault_services = ServiceProvider(
        use_case=None,
        persistence=FaultModulePersistenceService(repository=fault_repo),
        review=FaultModuleReviewService(repository=fault_repo),
        reconciliation=FaultModuleReconciliationService(repository=fault_repo),
        batch=None,
    )

    procedural_services = ProceduralServiceProvider(
        use_case=uc,
        persistence=persistence,
        batch=batch,
    )
    app = create_app(fault_services, procedural_services=procedural_services)
    return TestClient(app, raise_server_exceptions=False)


def _batch_body(*doc_ids: str) -> dict:
    """Minimal valid batch request body."""
    return {
        "items": [
            {
                "id": did,
                "full_text": f"Content for {did}.",
                "file_name": f"{did}.pdf",
            }
            for did in doc_ids
        ],
    }


class TestProceduralBatchAPI:
    """``POST /procedural/process/batch`` endpoint tests."""

    # 33
    def test_batch_success_all_items(self) -> None:
        client = _build_procedural_api_client()
        r = client.post("/procedural/process/batch", json=_batch_body("a", "b", "c"))
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3
        assert data["failed"] == 0
        assert len(data["items"]) == 3

    # 34
    def test_batch_partial_success(self) -> None:
        uc = _StubUseCase(fail_ids={"bad"})
        client = _build_procedural_api_client(use_case=uc)
        r = client.post("/procedural/process/batch", json=_batch_body("good", "bad"))
        assert r.status_code == 200
        data = r.json()
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        failed = [i for i in data["items"] if not i["success"]]
        assert len(failed) == 1
        assert failed[0]["source_id"] == "bad"

    # 35
    def test_batch_all_fail(self) -> None:
        uc = _StubUseCase(should_fail=True)
        client = _build_procedural_api_client(use_case=uc)
        r = client.post("/procedural/process/batch", json=_batch_body("x", "y"))
        assert r.status_code == 200
        data = r.json()
        assert data["succeeded"] == 0
        assert data["failed"] == 2

    # 36
    def test_batch_empty_items_422(self) -> None:
        client = _build_procedural_api_client()
        r = client.post("/procedural/process/batch", json={"items": []})
        assert r.status_code == 422

    # 37
    def test_batch_503_no_batch_service(self) -> None:
        client = _build_procedural_api_client(include_batch=False)
        r = client.post("/procedural/process/batch", json=_batch_body("x"))
        assert r.status_code == 503

    # 38
    def test_batch_response_shape(self) -> None:
        client = _build_procedural_api_client()
        r = client.post("/procedural/process/batch", json=_batch_body("doc-1"))
        data = r.json()
        assert "total" in data
        assert "succeeded" in data
        assert "failed" in data
        assert "persisted_trusted" in data
        assert "persisted_review" in data
        assert "not_persisted" in data
        assert "elapsed_ms" in data
        assert "items" in data
        item = data["items"][0]
        assert "source_id" in item
        assert "success" in item
        assert "record_id" in item
        assert "persisted" in item

    # 39
    def test_batch_single_item(self) -> None:
        client = _build_procedural_api_client()
        r = client.post("/procedural/process/batch", json=_batch_body("single"))
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["source_id"] == "single"

    # 40
    def test_batch_item_module_type_present(self) -> None:
        """Batch item response should include module_type."""
        client = _build_procedural_api_client()
        r = client.post("/procedural/process/batch", json=_batch_body("doc-1"))
        data = r.json()
        assert data["items"][0]["module_type"] == "procedural"


# ═══════════════════════════════════════════════════════════════════════
#  G. BATCH CLI COMMAND
# ═══════════════════════════════════════════════════════════════════════


class TestProceduralBatchCLI:
    """``process-procedural-batch`` CLI command tests."""

    def _run_cli(
        self,
        args: list[str],
        use_case: _StubUseCase | None = None,
        repo: FakeFaultModuleRepository | None = None,
    ) -> tuple[int, str, str]:
        from typer.testing import CliRunner

        repo = repo or FakeFaultModuleRepository()
        uc = use_case or _StubUseCase()
        persistence = ProceduralModulePersistenceService(repository=repo)
        batch = ProceduralBatchProcessingService(use_case=uc, persistence=persistence)

        services = ProceduralServiceProvider(
            use_case=uc,
            persistence=persistence,
            batch=batch,
        )
        cli_set_services(services)

        runner = CliRunner()
        result = runner.invoke(procedural_cli, args)
        return result.exit_code, result.stdout, result.stderr if hasattr(result, "stderr") else ""

    # 41
    def test_process_batch_success(self, tmp_path: Path) -> None:
        payload = [
            {"id": "doc-1", "full_text": "Content 1", "file_name": "a.pdf"},
            {"id": "doc-2", "full_text": "Content 2", "file_name": "b.pdf"},
        ]
        f = tmp_path / "batch.json"
        f.write_text(json.dumps(payload))

        code, stdout, _ = self._run_cli(["process-procedural-batch", str(f)])
        assert code == 0
        data = json.loads(stdout)
        assert data["total"] == 2
        assert data["succeeded"] == 2

    # 42
    def test_process_batch_partial_failure_exit_1(self, tmp_path: Path) -> None:
        uc = _StubUseCase(fail_ids={"doc-bad"})
        payload = [
            {"id": "doc-ok", "full_text": "ok", "file_name": "ok.pdf"},
            {"id": "doc-bad", "full_text": "bad", "file_name": "bad.pdf"},
        ]
        f = tmp_path / "batch.json"
        f.write_text(json.dumps(payload))

        code, stdout, _ = self._run_cli(["process-procedural-batch", str(f)], use_case=uc)
        assert code == 1
        data = json.loads(stdout)
        assert data["failed"] == 1

    # 43
    def test_process_batch_file_not_found(self) -> None:
        code, _, _ = self._run_cli(["process-procedural-batch", "/nonexistent/batch.json"])
        assert code == 1

    # 44
    def test_process_batch_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json!!!")
        code, _, _ = self._run_cli(["process-procedural-batch", str(f)])
        assert code == 1

    # 45
    def test_process_batch_non_array_json(self, tmp_path: Path) -> None:
        f = tmp_path / "obj.json"
        f.write_text(json.dumps({"id": "single", "full_text": "oops"}))
        code, _, _ = self._run_cli(["process-procedural-batch", str(f)])
        assert code == 1

    # 46
    def test_process_batch_empty_array(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text(json.dumps([]))
        code, _, _ = self._run_cli(["process-procedural-batch", str(f)])
        assert code == 1


# ═══════════════════════════════════════════════════════════════════════
#  H. ASYNC PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncProceduralPersistence:
    """Async ``AsyncProceduralModulePersistenceService`` tests."""

    # 47
    @pytest.mark.asyncio(loop_scope="function")
    async def test_approved_to_procedural_trusted(self) -> None:
        repo = AsyncFakeFaultModuleRepository()
        svc = AsyncProceduralModulePersistenceService(repository=repo)
        module = S1000DProceduralDataModule(
            record_id="REC-ASYNC-001",
            review_status=ReviewStatus.APPROVED,
            mapping_version="1.0.0",
        )
        result = await svc.persist(module)
        assert result.success is True
        assert result.collection == "procedural_trusted"

    # 48
    @pytest.mark.asyncio(loop_scope="function")
    async def test_not_reviewed_to_procedural_review(self) -> None:
        repo = AsyncFakeFaultModuleRepository()
        svc = AsyncProceduralModulePersistenceService(repository=repo)
        module = S1000DProceduralDataModule(
            record_id="REC-ASYNC-002",
            review_status=ReviewStatus.NOT_REVIEWED,
            mapping_version="1.0.0",
        )
        result = await svc.persist(module)
        assert result.success is True
        assert result.collection == "procedural_review"

    # 49
    @pytest.mark.asyncio(loop_scope="function")
    async def test_rejected_not_persisted(self) -> None:
        repo = AsyncFakeFaultModuleRepository()
        svc = AsyncProceduralModulePersistenceService(repository=repo)
        module = S1000DProceduralDataModule(
            record_id="REC-ASYNC-003",
            review_status=ReviewStatus.REJECTED,
            mapping_version="1.0.0",
        )
        result = await svc.persist(module)
        assert result.success is False

    # 50
    @pytest.mark.asyncio(loop_scope="function")
    async def test_retrieve_round_trip(self) -> None:
        repo = AsyncFakeFaultModuleRepository()
        svc = AsyncProceduralModulePersistenceService(repository=repo)
        module = S1000DProceduralDataModule(
            record_id="REC-ASYNC-RT",
            review_status=ReviewStatus.APPROVED,
            mapping_version="1.0.0",
        )
        await svc.persist(module)
        env = await svc.retrieve("REC-ASYNC-RT", "procedural_trusted")
        assert env is not None
        assert env.record_id == "REC-ASYNC-RT"
