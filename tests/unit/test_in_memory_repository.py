"""Tests for ``InMemoryFaultModuleRepository``.

Exercises the full ``FaultModuleRepositoryPort`` contract using the
in-memory implementation.  These tests also serve as the contract
spec — any new adapter must pass an equivalent suite.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.in_memory_repository import (
    InMemoryFaultModuleRepository,
)
from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.ports import FaultModuleRepositoryPort
from fault_mapper.domain.value_objects import PersistenceEnvelope
from tests.fixtures.persistence_fixtures import make_envelope


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def repo() -> InMemoryFaultModuleRepository:
    return InMemoryFaultModuleRepository()


# ═══════════════════════════════════════════════════════════════════════
#  PROTOCOL COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════


class TestProtocolCompliance:
    def test_satisfies_repository_port(self) -> None:
        repo = InMemoryFaultModuleRepository()
        assert isinstance(repo, FaultModuleRepositoryPort)


# ═══════════════════════════════════════════════════════════════════════
#  SAVE
# ═══════════════════════════════════════════════════════════════════════


class TestSave:
    def test_save_returns_success(self, repo: InMemoryFaultModuleRepository) -> None:
        env = make_envelope(record_id="R1")
        result = repo.save(env)
        assert result.success is True
        assert result.record_id == "R1"
        assert result.stored_at is not None

    def test_save_makes_envelope_retrievable(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        env = make_envelope(record_id="R1", collection="trusted")
        repo.save(env)
        retrieved = repo.get("R1", "trusted")
        assert retrieved is not None
        assert retrieved.record_id == "R1"

    def test_save_upserts_same_record(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        env1 = make_envelope(record_id="R1", mapping_version="1.0.0")
        env2 = make_envelope(record_id="R1", mapping_version="2.0.0")
        repo.save(env1)
        repo.save(env2)

        retrieved = repo.get("R1", "trusted")
        assert retrieved is not None
        assert retrieved.mapping_version == "2.0.0"
        assert repo.count("trusted") == 1

    def test_save_to_different_collections(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        trusted = make_envelope(record_id="R1", collection="trusted")
        review = make_envelope(record_id="R2", collection="review")
        repo.save(trusted)
        repo.save(review)

        assert repo.count("trusted") == 1
        assert repo.count("review") == 1

    def test_same_record_id_different_collections_coexist(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        """Same record_id in different collections are separate entries."""
        env_t = make_envelope(record_id="R1", collection="trusted")
        env_r = make_envelope(record_id="R1", collection="review")
        repo.save(env_t)
        repo.save(env_r)

        assert repo.count("trusted") == 1
        assert repo.count("review") == 1
        assert repo.get("R1", "trusted") is not None
        assert repo.get("R1", "review") is not None


# ═══════════════════════════════════════════════════════════════════════
#  GET
# ═══════════════════════════════════════════════════════════════════════


class TestGet:
    def test_get_missing_returns_none(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        assert repo.get("NONEXISTENT", "trusted") is None

    def test_get_wrong_collection_returns_none(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        env = make_envelope(record_id="R1", collection="trusted")
        repo.save(env)
        assert repo.get("R1", "review") is None

    def test_get_returns_exact_envelope(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        env = make_envelope(
            record_id="R1",
            collection="review",
            mapping_version="3.0.0",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        )
        repo.save(env)

        got = repo.get("R1", "review")
        assert got is not None
        assert got.mapping_version == "3.0.0"
        assert got.validation_status is ValidationStatus.REVIEW_REQUIRED


# ═══════════════════════════════════════════════════════════════════════
#  LIST_BY_COLLECTION
# ═══════════════════════════════════════════════════════════════════════


class TestListByCollection:
    def test_empty_collection(self, repo: InMemoryFaultModuleRepository) -> None:
        assert repo.list_by_collection("trusted") == []

    def test_returns_only_matching_collection(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="T1", collection="trusted"))
        repo.save(make_envelope(record_id="T2", collection="trusted"))
        repo.save(make_envelope(record_id="R1", collection="review"))

        trusted = repo.list_by_collection("trusted")
        assert len(trusted) == 2
        assert all(e.collection == "trusted" for e in trusted)

    def test_pagination_limit(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        for i in range(10):
            repo.save(make_envelope(
                record_id=f"T{i}",
                collection="trusted",
                stored_at=f"2026-01-01T{i:02d}:00:00+00:00",
            ))

        page = repo.list_by_collection("trusted", limit=3)
        assert len(page) == 3

    def test_pagination_offset(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        for i in range(5):
            repo.save(make_envelope(
                record_id=f"T{i}",
                collection="trusted",
                stored_at=f"2026-01-01T{i:02d}:00:00+00:00",
            ))

        all_envs = repo.list_by_collection("trusted", limit=100)
        page_2 = repo.list_by_collection("trusted", limit=2, offset=2)
        assert len(page_2) == 2
        assert page_2[0].record_id == all_envs[2].record_id

    def test_sorted_by_stored_at_descending(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(
            record_id="OLD", stored_at="2026-01-01T00:00:00+00:00",
        ))
        repo.save(make_envelope(
            record_id="NEW", stored_at="2026-06-01T00:00:00+00:00",
        ))

        listed = repo.list_by_collection("trusted")
        assert listed[0].record_id == "NEW"
        assert listed[1].record_id == "OLD"


# ═══════════════════════════════════════════════════════════════════════
#  COUNT
# ═══════════════════════════════════════════════════════════════════════


class TestCount:
    def test_empty(self, repo: InMemoryFaultModuleRepository) -> None:
        assert repo.count("trusted") == 0

    def test_after_saves(self, repo: InMemoryFaultModuleRepository) -> None:
        for i in range(4):
            repo.save(make_envelope(record_id=f"R{i}"))
        assert repo.count("trusted") == 4

    def test_count_per_collection(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="T1", collection="trusted"))
        repo.save(make_envelope(record_id="R1", collection="review"))
        repo.save(make_envelope(record_id="R2", collection="review"))

        assert repo.count("trusted") == 1
        assert repo.count("review") == 2


# ═══════════════════════════════════════════════════════════════════════
#  CLEAR (test helper)
# ═══════════════════════════════════════════════════════════════════════


class TestClear:
    def test_clear_removes_all(self, repo: InMemoryFaultModuleRepository) -> None:
        repo.save(make_envelope(record_id="R1"))
        repo.save(make_envelope(record_id="R2", collection="review"))
        assert len(repo.all_envelopes) == 2

        repo.clear()
        assert len(repo.all_envelopes) == 0
        assert repo.count("trusted") == 0
        assert repo.count("review") == 0


# ═══════════════════════════════════════════════════════════════════════
#  DELETE
# ═══════════════════════════════════════════════════════════════════════


class TestDelete:
    def test_delete_existing_returns_success(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="D1", collection="review"))
        result = repo.delete("D1", "review")
        assert result.success is True
        assert result.record_id == "D1"
        assert result.collection == "review"

    def test_delete_removes_from_store(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="D1", collection="review"))
        repo.delete("D1", "review")
        assert repo.get("D1", "review") is None
        assert repo.count("review") == 0

    def test_delete_nonexistent_returns_success(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        """Idempotent delete — missing key is not an error."""
        result = repo.delete("NOPE", "review")
        assert result.success is True

    def test_delete_does_not_affect_other_collections(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="D1", collection="trusted"))
        repo.save(make_envelope(record_id="D1", collection="review"))

        repo.delete("D1", "review")

        assert repo.get("D1", "trusted") is not None
        assert repo.get("D1", "review") is None

    def test_delete_updates_count(
        self, repo: InMemoryFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="D1", collection="review"))
        repo.save(make_envelope(record_id="D2", collection="review"))
        assert repo.count("review") == 2

        repo.delete("D1", "review")
        assert repo.count("review") == 1
