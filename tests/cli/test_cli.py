"""Tests for the Typer CLI layer (Chunk 15).

Uses Typer's ``CliRunner`` with in-memory services — no network,
no MongoDB, no LLM.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fault_mapper.adapters.primary.api.dependencies import ServiceProvider
from fault_mapper.adapters.primary.cli.main import cli, set_services
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

runner = CliRunner()


# ═══════════════════════════════════════════════════════════════════════
#  STUBS
# ═══════════════════════════════════════════════════════════════════════


class _StubUseCase:
    """Fake use case that returns a minimal module."""

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


@pytest.fixture()
def services(repo: FakeFaultModuleRepository):
    """Wire in-memory services with stub use case."""
    svc = ServiceProvider(
        use_case=_StubUseCase(),
        persistence=FaultModulePersistenceService(repository=repo),
        review=FaultModuleReviewService(repository=repo),
        reconciliation=FaultModuleReconciliationService(repository=repo),
    )
    set_services(svc)
    yield svc
    set_services(None)


@pytest.fixture()
def input_file(tmp_path: Path) -> Path:
    """Create a minimal valid input JSON file."""
    data = {
        "id": "doc-001",
        "full_text": "Fault troubleshooting.",
        "file_name": "test.pdf",
        "file_type": "pdf",
        "source_path": "/uploads/test.pdf",
        "sections": [],
    }
    p = tmp_path / "input.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ═══════════════════════════════════════════════════════════════════════
#  HEALTH
# ═══════════════════════════════════════════════════════════════════════


class TestHealthCLI:
    def test_health(self, services) -> None:
        result = runner.invoke(cli, ["health"])
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS
# ═══════════════════════════════════════════════════════════════════════


class TestProcessCLI:
    def test_process_success(
        self, services, input_file: Path,
    ) -> None:
        result = runner.invoke(cli, ["process", str(input_file)])
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["record_id"] == "REC-doc-001"
        assert body["persisted"] is True

    def test_process_file_not_found(self, services) -> None:
        result = runner.invoke(cli, ["process", "/nonexistent/file.json"])
        assert result.exit_code == 1

    def test_process_invalid_json(
        self, services, tmp_path: Path,
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        result = runner.invoke(cli, ["process", str(bad)])
        assert result.exit_code == 1

    def test_process_missing_id(
        self, services, tmp_path: Path,
    ) -> None:
        p = tmp_path / "no_id.json"
        p.write_text(json.dumps({"full_text": "x"}), encoding="utf-8")
        result = runner.invoke(cli, ["process", str(p)])
        assert result.exit_code == 1

    def test_process_mapping_failure(
        self, repo: FakeFaultModuleRepository, input_file: Path,
    ) -> None:
        svc = ServiceProvider(
            use_case=_StubUseCase(should_fail=True),
            persistence=FaultModulePersistenceService(repository=repo),
            review=FaultModuleReviewService(repository=repo),
            reconciliation=FaultModuleReconciliationService(repository=repo),
        )
        set_services(svc)
        result = runner.invoke(cli, ["process", str(input_file)])
        assert result.exit_code == 1
        set_services(None)

    def test_process_no_use_case(
        self, repo: FakeFaultModuleRepository, input_file: Path,
    ) -> None:
        svc = ServiceProvider(
            use_case=None,
            persistence=FaultModulePersistenceService(repository=repo),
            review=FaultModuleReviewService(repository=repo),
            reconciliation=FaultModuleReconciliationService(repository=repo),
        )
        set_services(svc)
        result = runner.invoke(cli, ["process", str(input_file)])
        assert result.exit_code == 1
        set_services(None)


# ═══════════════════════════════════════════════════════════════════════
#  APPROVE / REJECT
# ═══════════════════════════════════════════════════════════════════════


class TestApproveCLI:
    def test_approve_success(
        self,
        services,
        repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(
            record_id="R-100",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
        ))
        result = runner.invoke(cli, ["approve", "R-100"])
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["success"] is True

    def test_approve_missing(self, services) -> None:
        result = runner.invoke(cli, ["approve", "NOPE"])
        assert result.exit_code == 1


class TestRejectCLI:
    def test_reject_success(
        self,
        services,
        repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(
            record_id="R-200",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
        ))
        result = runner.invoke(
            cli, ["reject", "R-200", "--reason", "Bad data"],
        )
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["success"] is True

    def test_reject_missing(self, services) -> None:
        result = runner.invoke(cli, ["reject", "NOPE"])
        assert result.exit_code == 1


# ═══════════════════════════════════════════════════════════════════════
#  SWEEP
# ═══════════════════════════════════════════════════════════════════════


class TestSweepCLI:
    def test_sweep_empty(self, services) -> None:
        result = runner.invoke(cli, ["sweep"])
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["total_review_scanned"] == 0

    def test_sweep_dry_run(self, services) -> None:
        result = runner.invoke(cli, ["sweep", "--dry-run"])
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["dry_run"] is True

    def test_sweep_with_orphans(
        self,
        services,
        repo: FakeFaultModuleRepository,
    ) -> None:
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
        result = runner.invoke(cli, ["sweep"])
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["duplicates_cleaned"] >= 1


# ═══════════════════════════════════════════════════════════════════════
#  OUTPUT FORMAT
# ═══════════════════════════════════════════════════════════════════════


class TestOutputFormat:
    """CLI output should always be valid JSON."""

    def test_health_is_json(self, services) -> None:
        result = runner.invoke(cli, ["health"])
        json.loads(result.stdout)  # must not raise

    def test_approve_error_is_json(self, services) -> None:
        result = runner.invoke(cli, ["approve", "MISSING"])
        # stdout has the JSON output
        body = json.loads(result.stdout)
        assert body["success"] is False
