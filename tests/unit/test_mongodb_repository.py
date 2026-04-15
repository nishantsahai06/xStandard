"""Tests for ``MongoDBFaultModuleRepository``.

These tests validate the MongoDB adapter at the integration level.
They use a **mock pymongo client** (dict-backed stub) so no real
MongoDB instance is required.

The adapter is also tested for protocol compliance.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from fault_mapper.adapters.secondary.mongodb_repository import (
    MongoDBFaultModuleRepository,
)
from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.ports import FaultModuleRepositoryPort
from fault_mapper.infrastructure.config import MongoConfig
from tests.fixtures.persistence_fixtures import make_envelope


# ═══════════════════════════════════════════════════════════════════════
#  SIMPLE IN-PROCESS MONGO STUB
# ═══════════════════════════════════════════════════════════════════════


class _StubCollection:
    """Minimal pymongo-Collection-like stub backed by a dict."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> None:
        key = filter["_id"]
        if key in self._docs or upsert:
            self._docs[key] = dict(replacement)

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None:
        return self._docs.get(filter["_id"])

    def find(self) -> "_StubCursor":
        return _StubCursor(list(self._docs.values()))

    def count_documents(self, _filter: dict[str, Any]) -> int:
        return len(self._docs)

    def delete_one(self, filter: dict[str, Any]) -> None:
        key = filter["_id"]
        self._docs.pop(key, None)

    def create_index(self, key: str, **kwargs: Any) -> None:
        pass  # no-op for stub


class _StubCursor:
    """Minimal cursor supporting sort/skip/limit chaining."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = list(docs)

    def sort(self, key: str, direction: int) -> "_StubCursor":
        self._docs.sort(
            key=lambda d: d.get(key, ""),
            reverse=(direction == -1),
        )
        return self

    def skip(self, n: int) -> "_StubCursor":
        self._docs = self._docs[n:]
        return self

    def limit(self, n: int) -> "_StubCursor":
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _StubDatabase:
    """Minimal pymongo-Database-like stub."""

    def __init__(self) -> None:
        self._collections: dict[str, _StubCollection] = {}

    def __getitem__(self, name: str) -> _StubCollection:
        if name not in self._collections:
            self._collections[name] = _StubCollection()
        return self._collections[name]


class _StubClient:
    """Minimal pymongo-MongoClient-like stub."""

    def __init__(self) -> None:
        self._databases: dict[str, _StubDatabase] = {}

    def __getitem__(self, name: str) -> _StubDatabase:
        if name not in self._databases:
            self._databases[name] = _StubDatabase()
        return self._databases[name]


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def mongo_config() -> MongoConfig:
    return MongoConfig(
        connection_uri="mongodb://stub:27017",
        database_name="test_fault_mapper",
        trusted_collection="test_trusted",
        review_collection="test_review",
    )


@pytest.fixture
def stub_client() -> _StubClient:
    return _StubClient()


@pytest.fixture
def repo(
    mongo_config: MongoConfig, stub_client: _StubClient,
) -> MongoDBFaultModuleRepository:
    return MongoDBFaultModuleRepository(
        config=mongo_config,
        client=stub_client,
    )


# ═══════════════════════════════════════════════════════════════════════
#  PROTOCOL COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════


class TestProtocolCompliance:
    def test_satisfies_repository_port(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        assert isinstance(repo, FaultModuleRepositoryPort)


# ═══════════════════════════════════════════════════════════════════════
#  SAVE
# ═══════════════════════════════════════════════════════════════════════


class TestSave:
    def test_save_returns_success(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        env = make_envelope(record_id="R1")
        result = repo.save(env)
        assert result.success is True
        assert result.record_id == "R1"
        assert result.stored_at is not None

    def test_save_makes_retrievable(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        env = make_envelope(record_id="R1", collection="trusted")
        repo.save(env)
        got = repo.get("R1", "trusted")
        assert got is not None
        assert got.record_id == "R1"

    def test_save_stores_document_payload(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        doc = {"recordId": "R1", "data": "payload"}
        env = make_envelope(record_id="R1", document=doc)
        repo.save(env)
        got = repo.get("R1", "trusted")
        assert got is not None
        assert got.document["data"] == "payload"

    def test_upsert_replaces(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        env1 = make_envelope(record_id="R1", mapping_version="1.0")
        env2 = make_envelope(record_id="R1", mapping_version="2.0")
        repo.save(env1)
        repo.save(env2)

        got = repo.get("R1", "trusted")
        assert got is not None
        assert got.mapping_version == "2.0"
        assert repo.count("trusted") == 1

    def test_saves_to_correct_physical_collection(
        self,
        mongo_config: MongoConfig,
        stub_client: _StubClient,
    ) -> None:
        """Verify logical → physical collection mapping."""
        repo = MongoDBFaultModuleRepository(
            config=mongo_config, client=stub_client,
        )
        repo.save(make_envelope(record_id="T1", collection="trusted"))
        repo.save(make_envelope(record_id="R1", collection="review"))

        db = stub_client[mongo_config.database_name]
        trusted_coll = db[mongo_config.trusted_collection]
        review_coll = db[mongo_config.review_collection]

        assert trusted_coll.find_one({"_id": "T1"}) is not None
        assert review_coll.find_one({"_id": "R1"}) is not None


# ═══════════════════════════════════════════════════════════════════════
#  GET
# ═══════════════════════════════════════════════════════════════════════


class TestGet:
    def test_get_missing_returns_none(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        assert repo.get("NONEXISTENT", "trusted") is None

    def test_get_wrong_collection(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="R1", collection="trusted"))
        assert repo.get("R1", "review") is None

    def test_get_preserves_metadata(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        env = make_envelope(
            record_id="R1",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
            mapping_version="3.0",
            stored_at="2026-04-13T12:00:00+00:00",
        )
        repo.save(env)
        got = repo.get("R1", "review")
        assert got is not None
        assert got.validation_status is ValidationStatus.REVIEW_REQUIRED
        assert got.review_status is ReviewStatus.NOT_REVIEWED
        assert got.mapping_version == "3.0"
        assert got.stored_at == "2026-04-13T12:00:00+00:00"


# ═══════════════════════════════════════════════════════════════════════
#  LIST BY COLLECTION
# ═══════════════════════════════════════════════════════════════════════


class TestListByCollection:
    def test_empty(self, repo: MongoDBFaultModuleRepository) -> None:
        assert repo.list_by_collection("trusted") == []

    def test_returns_correct_collection(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="T1", collection="trusted"))
        repo.save(make_envelope(record_id="T2", collection="trusted"))
        repo.save(make_envelope(record_id="R1", collection="review"))

        trusted = repo.list_by_collection("trusted")
        assert len(trusted) == 2

    def test_pagination(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        for i in range(5):
            repo.save(make_envelope(record_id=f"T{i}"))

        page = repo.list_by_collection("trusted", limit=2, offset=1)
        assert len(page) == 2


# ═══════════════════════════════════════════════════════════════════════
#  COUNT
# ═══════════════════════════════════════════════════════════════════════


class TestCount:
    def test_empty(self, repo: MongoDBFaultModuleRepository) -> None:
        assert repo.count("trusted") == 0

    def test_after_saves(self, repo: MongoDBFaultModuleRepository) -> None:
        for i in range(3):
            repo.save(make_envelope(record_id=f"R{i}"))
        assert repo.count("trusted") == 3


# ═══════════════════════════════════════════════════════════════════════
#  ENSURE INDEXES
# ═══════════════════════════════════════════════════════════════════════


class TestEnsureIndexes:
    def test_ensure_indexes_does_not_raise(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        """Smoke test — idempotent, should not error."""
        repo.ensure_indexes()
        repo.ensure_indexes()  # call twice to verify idempotency


# ═══════════════════════════════════════════════════════════════════════
#  DOCUMENT SHAPE
# ═══════════════════════════════════════════════════════════════════════


class TestDocumentShape:
    """Verify the MongoDB document has the expected structure."""

    def test_stored_document_has_expected_keys(
        self,
        repo: MongoDBFaultModuleRepository,
        stub_client: _StubClient,
        mongo_config: MongoConfig,
    ) -> None:
        repo.save(make_envelope(record_id="R1"))

        db = stub_client[mongo_config.database_name]
        coll = db[mongo_config.trusted_collection]
        doc = coll.find_one({"_id": "R1"})

        assert doc is not None
        expected_keys = {
            "_id", "record_id", "collection", "validation_status",
            "review_status", "mapping_version", "stored_at", "document",
        }
        assert expected_keys == set(doc.keys())

    def test_validation_status_stored_as_string(
        self,
        repo: MongoDBFaultModuleRepository,
        stub_client: _StubClient,
        mongo_config: MongoConfig,
    ) -> None:
        repo.save(make_envelope(record_id="R1"))

        db = stub_client[mongo_config.database_name]
        coll = db[mongo_config.trusted_collection]
        doc = coll.find_one({"_id": "R1"})

        assert doc is not None
        assert doc["validation_status"] == "approved"
        assert doc["review_status"] == "approved"


# ═══════════════════════════════════════════════════════════════════════
#  DELETE
# ═══════════════════════════════════════════════════════════════════════


class TestDelete:
    def test_delete_existing_returns_success(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="D1", collection="review"))
        result = repo.delete("D1", "review")
        assert result.success is True
        assert result.record_id == "D1"

    def test_delete_removes_from_store(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="D1", collection="review"))
        repo.delete("D1", "review")
        assert repo.get("D1", "review") is None
        assert repo.count("review") == 0

    def test_delete_nonexistent_returns_success(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        result = repo.delete("NOPE", "review")
        assert result.success is True

    def test_delete_does_not_affect_other_collections(
        self, repo: MongoDBFaultModuleRepository,
    ) -> None:
        repo.save(make_envelope(record_id="D1", collection="trusted"))
        repo.save(make_envelope(record_id="D1", collection="review"))

        repo.delete("D1", "review")

        assert repo.get("D1", "trusted") is not None
        assert repo.get("D1", "review") is None

    def test_delete_exception_returns_failure(
        self, mongo_config: MongoConfig,
    ) -> None:
        """Simulated backend error on delete."""
        error_client = _StubClient()
        repo = MongoDBFaultModuleRepository(
            config=mongo_config, client=error_client,
        )
        repo.save(make_envelope(record_id="D1", collection="review"))

        # Monkey-patch to simulate failure
        coll = error_client[mongo_config.database_name][
            mongo_config.review_collection
        ]
        original_delete = coll.delete_one
        coll.delete_one = MagicMock(
            side_effect=RuntimeError("disk full"),
        )

        result = repo.delete("D1", "review")
        assert result.success is False
        assert "disk full" in result.error
