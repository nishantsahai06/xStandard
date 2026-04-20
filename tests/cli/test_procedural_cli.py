"""Tests for the procedural Typer CLI layer (Chunk 8).

Uses Typer's ``CliRunner`` with in-memory services — no network,
no MongoDB, no LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fault_mapper.adapters.primary.api.procedural_dependencies import (
    ProceduralServiceProvider,
)
from fault_mapper.adapters.primary.cli.procedural_main import (
    procedural_cli,
    set_procedural_services,
)
from fault_mapper.application.procedural_module_persistence_service import (
    ProceduralModulePersistenceService,
)
from fault_mapper.domain.enums import ReviewStatus
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository

runner = CliRunner()


# ═══════════════════════════════════════════════════════════════════════
#  STUBS
# ═══════════════════════════════════════════════════════════════════════


class _StubProceduralUseCase:
    """Fake procedural use case."""

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


@pytest.fixture()
def services(repo: FakeFaultModuleRepository):
    """Wire in-memory services with stub use case."""
    svc = ProceduralServiceProvider(
        use_case=_StubProceduralUseCase(),
        persistence=ProceduralModulePersistenceService(repository=repo),
    )
    set_procedural_services(svc)
    yield svc
    set_procedural_services(None)


@pytest.fixture()
def input_file(tmp_path: Path) -> Path:
    """Create a minimal valid input JSON file."""
    data = {
        "id": "proc-001",
        "full_text": "Remove and replace the oil filter.",
        "file_name": "maintenance.pdf",
        "file_type": "pdf",
        "source_path": "/uploads/maintenance.pdf",
        "sections": [],
    }
    p = tmp_path / "input.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS PROCEDURAL
# ═══════════════════════════════════════════════════════════════════════


class TestProcessProceduralCLI:
    def test_process_success(self, services, input_file: Path) -> None:
        result = runner.invoke(
            procedural_cli, ["process-procedural", str(input_file)],
        )
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["record_id"] == "REC-PROC-proc-001"
        assert body["module_type"] == "procedural"
        assert body["persisted"] is True
        assert body["collection"] == "procedural_trusted"

    def test_process_review_path(
        self, repo: FakeFaultModuleRepository, input_file: Path,
    ) -> None:
        svc = ProceduralServiceProvider(
            use_case=_StubProceduralUseCase(review_status=ReviewStatus.NOT_REVIEWED),
            persistence=ProceduralModulePersistenceService(repository=repo),
        )
        set_procedural_services(svc)
        result = runner.invoke(
            procedural_cli, ["process-procedural", str(input_file)],
        )
        assert result.exit_code == 0
        body = json.loads(result.stdout)
        assert body["review_status"] == "not_reviewed"
        assert body["collection"] == "procedural_review"
        set_procedural_services(None)

    def test_process_file_not_found(self, services) -> None:
        result = runner.invoke(
            procedural_cli, ["process-procedural", "/nonexistent/file.json"],
        )
        assert result.exit_code == 1

    def test_process_invalid_json(self, services, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        result = runner.invoke(
            procedural_cli, ["process-procedural", str(bad)],
        )
        assert result.exit_code == 1

    def test_process_missing_id(self, services, tmp_path: Path) -> None:
        p = tmp_path / "no_id.json"
        p.write_text(json.dumps({"full_text": "x"}), encoding="utf-8")
        result = runner.invoke(
            procedural_cli, ["process-procedural", str(p)],
        )
        assert result.exit_code == 1

    def test_process_mapping_failure(
        self, repo: FakeFaultModuleRepository, input_file: Path,
    ) -> None:
        svc = ProceduralServiceProvider(
            use_case=_StubProceduralUseCase(should_fail=True),
            persistence=ProceduralModulePersistenceService(repository=repo),
        )
        set_procedural_services(svc)
        result = runner.invoke(
            procedural_cli, ["process-procedural", str(input_file)],
        )
        assert result.exit_code == 1
        set_procedural_services(None)

    def test_process_no_use_case(
        self, repo: FakeFaultModuleRepository, input_file: Path,
    ) -> None:
        svc = ProceduralServiceProvider(
            use_case=None,
            persistence=ProceduralModulePersistenceService(repository=repo),
        )
        set_procedural_services(svc)
        result = runner.invoke(
            procedural_cli, ["process-procedural", str(input_file)],
        )
        assert result.exit_code == 1
        set_procedural_services(None)


# ═══════════════════════════════════════════════════════════════════════
#  OUTPUT FORMAT
# ═══════════════════════════════════════════════════════════════════════


class TestProceduralOutputFormat:
    """CLI output should always be valid JSON."""

    def test_success_is_json(self, services, input_file: Path) -> None:
        result = runner.invoke(
            procedural_cli, ["process-procedural", str(input_file)],
        )
        body = json.loads(result.stdout)
        expected_keys = {
            "record_id", "module_type", "review_status",
            "persisted", "collection", "persistence_error",
            "mapping_version",
        }
        assert set(body.keys()) == expected_keys

    def test_response_shape_review_path(
        self, repo: FakeFaultModuleRepository, input_file: Path,
    ) -> None:
        svc = ProceduralServiceProvider(
            use_case=_StubProceduralUseCase(review_status=ReviewStatus.NOT_REVIEWED),
            persistence=ProceduralModulePersistenceService(repository=repo),
        )
        set_procedural_services(svc)
        result = runner.invoke(
            procedural_cli, ["process-procedural", str(input_file)],
        )
        body = json.loads(result.stdout)
        assert body["module_type"] == "procedural"
        assert body["persistence_error"] is None
        set_procedural_services(None)
