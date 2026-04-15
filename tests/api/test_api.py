"""Tests for the HTTP API layer (Chunk 15).

Uses FastAPI's ``TestClient`` with in-memory services — no network,
no MongoDB, no LLM.

Strategy:
  - A stub ``FaultMappingUseCase`` replaces the real pipeline so we
    can control outcomes without LLM dependencies.
  - Real ``FaultModulePersistenceService``, ``FaultModuleReviewService``,
    and ``FaultModuleReconciliationService`` are wired with the
    ``FakeFaultModuleRepository``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fault_mapper.adapters.primary.api.app import create_app
from fault_mapper.adapters.primary.api.dependencies import ServiceProvider
from fault_mapper.application.fault_module_persistence_service import (
    FaultModulePersistenceService,
)
from fault_mapper.application.fault_module_reconciliation_service import (
    FaultModuleReconciliationService,
)
from fault_mapper.application.fault_module_review_service import (
    FaultModuleReviewService,
)
from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.models import S1000DFaultDataModule
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.persistence_fixtures import make_envelope


# ═══════════════════════════════════════════════════════════════════════
#  STUBS
# ═══════════════════════════════════════════════════════════════════════


class _StubUseCase:
    """Fake mapping use case that returns a minimal module."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        status: ValidationStatus = ValidationStatus.APPROVED,
    ) -> None:
        self._should_fail = should_fail
        self._status = status

    def execute(self, source):
        if self._should_fail:
            raise ValueError("No fault-relevant sections found in document")
        return S1000DFaultDataModule(
            record_id=f"REC-{source.id}",
            validation_status=self._status,
            review_status=ReviewStatus.APPROVED
            if self._status == ValidationStatus.APPROVED
            else ReviewStatus.NOT_REVIEWED,
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
    services = ServiceProvider(
        use_case=use_case or _StubUseCase(),
        persistence=FaultModulePersistenceService(repository=repo),
        review=FaultModuleReviewService(repository=repo),
        reconciliation=FaultModuleReconciliationService(repository=repo),
    )
    app = create_app(services)
    return TestClient(app, raise_server_exceptions=False)


def _minimal_process_body(**overrides) -> dict:
    """Minimal valid ``ProcessRequest`` body."""
    defaults = {
        "id": "doc-001",
        "full_text": "Fault troubleshooting content.",
        "file_name": "test.pdf",
    }
    defaults.update(overrides)
    return defaults


# ═══════════════════════════════════════════════════════════════════════
#  HEALTH
# ═══════════════════════════════════════════════════════════════════════


class TestHealth:
    def test_health_ok(self, repo: FakeFaultModuleRepository) -> None:
        client = _build_client(repo)
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS
# ═══════════════════════════════════════════════════════════════════════


class TestProcess:
    def test_process_success(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.post("/process", json=_minimal_process_body())
        assert r.status_code == 200
        body = r.json()
        assert body["record_id"] == "REC-doc-001"
        assert body["validation_status"] == "stored"  # APPROVED → persist → STORED
        assert body["persisted"] is True
        assert body["collection"] == "trusted"

    def test_process_review_required(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        stub = _StubUseCase(status=ValidationStatus.REVIEW_REQUIRED)
        client = _build_client(repo, use_case=stub)
        r = client.post("/process", json=_minimal_process_body())
        assert r.status_code == 200
        body = r.json()
        assert body["validation_status"] == "review_required"
        assert body["collection"] == "review"
        assert body["persisted"] is True

    def test_process_mapping_failure(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        stub = _StubUseCase(should_fail=True)
        client = _build_client(repo, use_case=stub)
        r = client.post("/process", json=_minimal_process_body())
        assert r.status_code == 400
        assert "fault-relevant sections" in r.json()["detail"].lower()

    def test_process_invalid_body(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.post("/process", json={"bad": True})
        assert r.status_code == 422

    def test_process_no_use_case(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        """When no LLM → use_case is None → 503."""
        services = ServiceProvider(
            use_case=None,
            persistence=FaultModulePersistenceService(repository=repo),
            review=FaultModuleReviewService(repository=repo),
            reconciliation=FaultModuleReconciliationService(repository=repo),
        )
        app = create_app(services)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/process", json=_minimal_process_body())
        assert r.status_code == 503


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW — APPROVE
# ═══════════════════════════════════════════════════════════════════════


class TestApprove:
    def test_approve_success(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(
            record_id="R-001",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
        ))
        client = _build_client(repo)
        r = client.post("/review/R-001/approve")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["record_id"] == "R-001"

    def test_approve_missing(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.post("/review/NOPE/approve")
        assert r.status_code == 404

    def test_approve_with_body(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(
            record_id="R-002",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
        ))
        client = _build_client(repo)
        r = client.post(
            "/review/R-002/approve",
            json={"reason": "Looks good", "performed_by": "alice"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW — REJECT
# ═══════════════════════════════════════════════════════════════════════


class TestReject:
    def test_reject_success(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(
            record_id="R-003",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
        ))
        client = _build_client(repo)
        r = client.post(
            "/review/R-003/reject",
            json={"reason": "Bad data"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_reject_missing(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.post("/review/NOPE/reject")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW — GET / LIST
# ═══════════════════════════════════════════════════════════════════════


class TestReviewList:
    def test_get_review_item(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(
            record_id="R-010",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
        ))
        client = _build_client(repo)
        r = client.get("/review/R-010")
        assert r.status_code == 200
        body = r.json()
        assert body["record_id"] == "R-010"
        assert body["collection"] == "review"

    def test_get_review_item_missing(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.get("/review/NOPE")
        assert r.status_code == 404

    def test_list_review_items_empty(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.get("/review")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["count"] == 0

    def test_list_review_items_populated(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        for i in range(3):
            repo.save(make_envelope(
                record_id=f"R-{i:03d}",
                collection="review",
                validation_status=ValidationStatus.REVIEW_REQUIRED,
                review_status=ReviewStatus.NOT_REVIEWED,
            ))
        client = _build_client(repo)
        r = client.get("/review")
        assert r.status_code == 200
        assert r.json()["count"] == 3


# ═══════════════════════════════════════════════════════════════════════
#  RECONCILIATION — SWEEP
# ═══════════════════════════════════════════════════════════════════════


class TestSweep:
    def test_sweep_empty(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.post("/reconciliation/sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["total_review_scanned"] == 0
        assert body["dry_run"] is False

    def test_sweep_dry_run(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.post(
            "/reconciliation/sweep",
            json={"dry_run": True},
        )
        assert r.status_code == 200
        assert r.json()["dry_run"] is True

    def test_sweep_cleans_orphans(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        # Seed an orphan: same record in both trusted and review
        repo.save(make_envelope(
            record_id="ORPHAN-1",
            collection="trusted",
            validation_status=ValidationStatus.APPROVED,
            review_status=ReviewStatus.APPROVED,
        ))
        repo.save(make_envelope(
            record_id="ORPHAN-1",
            collection="review",
            validation_status=ValidationStatus.APPROVED,
            review_status=ReviewStatus.APPROVED,
        ))
        client = _build_client(repo)
        r = client.post("/reconciliation/sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["duplicates_found"] >= 1
        assert body["duplicates_cleaned"] >= 1


# ═══════════════════════════════════════════════════════════════════════
#  RECONCILIATION — ORPHANS
# ═══════════════════════════════════════════════════════════════════════


class TestOrphans:
    def test_orphans_empty(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.get("/reconciliation/orphans")
        assert r.status_code == 200
        body = r.json()
        assert body["orphan_ids"] == []
        assert body["count"] == 0

    def test_orphans_found(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(
            record_id="ORPHAN-2",
            collection="trusted",
            validation_status=ValidationStatus.APPROVED,
            review_status=ReviewStatus.APPROVED,
        ))
        repo.save(make_envelope(
            record_id="ORPHAN-2",
            collection="review",
            validation_status=ValidationStatus.APPROVED,
            review_status=ReviewStatus.APPROVED,
        ))
        client = _build_client(repo)
        r = client.get("/reconciliation/orphans")
        assert r.status_code == 200
        body = r.json()
        assert "ORPHAN-2" in body["orphan_ids"]
        assert body["count"] >= 1


# ═══════════════════════════════════════════════════════════════════════
#  ERROR RESPONSE SHAPE
# ═══════════════════════════════════════════════════════════════════════


class TestErrorShape:
    def test_404_has_detail(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.get("/review/MISSING")
        assert r.status_code == 404
        body = r.json()
        assert "detail" in body

    def test_422_validation_error(
        self, repo: FakeFaultModuleRepository,
    ) -> None:
        client = _build_client(repo)
        r = client.post("/process", json={"not_id": "x"})
        assert r.status_code == 422
        body = r.json()
        # FastAPI returns "detail" for validation errors
        assert "detail" in body
