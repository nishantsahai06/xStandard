"""Tests for the procedural HTTP API layer (Chunk 8).

Uses FastAPI's ``TestClient`` with in-memory services — no network,
no MongoDB, no LLM.

Strategy:
  - A stub ``ProceduralMappingUseCase`` replaces the real pipeline.
  - Real ``ProceduralModulePersistenceService`` is wired with
    ``FakeFaultModuleRepository``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fault_mapper.adapters.primary.api.app import create_app
from fault_mapper.adapters.primary.api.dependencies import ServiceProvider
from fault_mapper.adapters.primary.api.procedural_dependencies import (
    ProceduralServiceProvider,
)
from fault_mapper.application.fault_module_persistence_service import (
    FaultModulePersistenceService,
)
from fault_mapper.application.fault_module_reconciliation_service import (
    FaultModuleReconciliationService,
)
from fault_mapper.application.fault_module_review_service import (
    FaultModuleReviewService,
)
from fault_mapper.application.procedural_module_persistence_service import (
    ProceduralModulePersistenceService,
)
from fault_mapper.domain.enums import ReviewStatus
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.procedural_persistence_fixtures import make_procedural_envelope


# ═══════════════════════════════════════════════════════════════════════
#  STUBS
# ═══════════════════════════════════════════════════════════════════════


class _StubProceduralUseCase:
    """Fake procedural use case that returns a minimal module."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        review_status: ReviewStatus = ReviewStatus.APPROVED,
    ) -> None:
        self._should_fail = should_fail
        self._review_status = review_status

    def execute(self, source, module_type=None):
        if self._should_fail:
            raise ValueError(
                "No procedural-relevant sections found in document"
            )
        return S1000DProceduralDataModule(
            record_id=f"REC-PROC-{source.id}",
            review_status=self._review_status,
            mapping_version="1.0.0",
        )


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def repo() -> FakeFaultModuleRepository:
    return FakeFaultModuleRepository()


def _build_client(
    repo: FakeFaultModuleRepository,
    use_case=None,
) -> TestClient:
    """Build a ``TestClient`` with wired in-memory services."""
    # Fault services still needed for the shared app
    fault_services = ServiceProvider(
        use_case=None,
        persistence=FaultModulePersistenceService(repository=repo),
        review=FaultModuleReviewService(repository=repo),
        reconciliation=FaultModuleReconciliationService(repository=repo),
    )
    proc_services = ProceduralServiceProvider(
        use_case=use_case or _StubProceduralUseCase(),
        persistence=ProceduralModulePersistenceService(repository=repo),
    )
    app = create_app(fault_services, procedural_services=proc_services)
    return TestClient(app, raise_server_exceptions=False)


def _minimal_process_body(**overrides) -> dict:
    """Minimal valid ``ProcessRequest`` body for procedural."""
    defaults = {
        "id": "proc-001",
        "full_text": "Remove and replace the oil filter.",
        "file_name": "maintenance.pdf",
    }
    defaults.update(overrides)
    return defaults


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS — PROCEDURAL
# ═══════════════════════════════════════════════════════════════════════


class TestProceduralProcess:
    def test_process_success(self, repo: FakeFaultModuleRepository) -> None:
        client = _build_client(repo)
        r = client.post("/procedural/process", json=_minimal_process_body())
        assert r.status_code == 200
        body = r.json()
        assert body["record_id"] == "REC-PROC-proc-001"
        assert body["module_type"] == "procedural"
        assert body["review_status"] == "approved"
        assert body["persisted"] is True
        assert body["collection"] == "procedural_trusted"

    def test_process_review_required(self, repo: FakeFaultModuleRepository) -> None:
        stub = _StubProceduralUseCase(review_status=ReviewStatus.NOT_REVIEWED)
        client = _build_client(repo, use_case=stub)
        r = client.post("/procedural/process", json=_minimal_process_body())
        assert r.status_code == 200
        body = r.json()
        assert body["review_status"] == "not_reviewed"
        assert body["collection"] == "procedural_review"
        assert body["persisted"] is True

    def test_process_mapping_failure(self, repo: FakeFaultModuleRepository) -> None:
        stub = _StubProceduralUseCase(should_fail=True)
        client = _build_client(repo, use_case=stub)
        r = client.post("/procedural/process", json=_minimal_process_body())
        assert r.status_code == 400
        assert "procedural-relevant sections" in r.json()["detail"].lower()

    def test_process_invalid_body(self, repo: FakeFaultModuleRepository) -> None:
        client = _build_client(repo)
        r = client.post("/procedural/process", json={"bad": True})
        assert r.status_code == 422

    def test_process_no_use_case(self, repo: FakeFaultModuleRepository) -> None:
        """When no LLM → use_case is None → 503."""
        client = _build_client(repo, use_case=None)
        # Rebuild with None use case
        fault_services = ServiceProvider(
            use_case=None,
            persistence=FaultModulePersistenceService(repository=repo),
            review=FaultModuleReviewService(repository=repo),
            reconciliation=FaultModuleReconciliationService(repository=repo),
        )
        proc_services = ProceduralServiceProvider(
            use_case=None,
            persistence=ProceduralModulePersistenceService(repository=repo),
        )
        app = create_app(fault_services, procedural_services=proc_services)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/procedural/process", json=_minimal_process_body())
        assert r.status_code == 503

    def test_response_shape(self, repo: FakeFaultModuleRepository) -> None:
        client = _build_client(repo)
        r = client.post("/procedural/process", json=_minimal_process_body())
        body = r.json()
        expected_keys = {
            "record_id", "module_type", "review_status",
            "persisted", "collection", "persistence_error",
            "mapping_version",
        }
        assert set(body.keys()) == expected_keys


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW — READ-ONLY
# ═══════════════════════════════════════════════════════════════════════


class TestProceduralReview:
    def test_get_review_item(self, repo: FakeFaultModuleRepository) -> None:
        repo.save(make_procedural_envelope(
            record_id="R-PROC-010",
            collection="procedural_review",
            review_status=ReviewStatus.NOT_REVIEWED,
        ))
        client = _build_client(repo)
        r = client.get("/procedural/review/R-PROC-010")
        assert r.status_code == 200
        body = r.json()
        assert body["record_id"] == "R-PROC-010"
        assert body["collection"] == "procedural_review"

    def test_get_review_item_missing(self, repo: FakeFaultModuleRepository) -> None:
        client = _build_client(repo)
        r = client.get("/procedural/review/NOPE")
        assert r.status_code == 404

    def test_list_review_items_empty(self, repo: FakeFaultModuleRepository) -> None:
        client = _build_client(repo)
        r = client.get("/procedural/review")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["count"] == 0

    def test_list_review_items_populated(self, repo: FakeFaultModuleRepository) -> None:
        for i in range(3):
            repo.save(make_procedural_envelope(
                record_id=f"R-PROC-{i:03d}",
                collection="procedural_review",
                review_status=ReviewStatus.NOT_REVIEWED,
            ))
        client = _build_client(repo)
        r = client.get("/procedural/review")
        assert r.status_code == 200
        assert r.json()["count"] == 3


# ═══════════════════════════════════════════════════════════════════════
#  ERROR SHAPE
# ═══════════════════════════════════════════════════════════════════════


class TestProceduralErrorShape:
    def test_404_has_detail(self, repo: FakeFaultModuleRepository) -> None:
        client = _build_client(repo)
        r = client.get("/procedural/review/MISSING")
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_422_validation_error(self, repo: FakeFaultModuleRepository) -> None:
        client = _build_client(repo)
        r = client.post("/procedural/process", json={"not_id": "x"})
        assert r.status_code == 422
        assert "detail" in r.json()
