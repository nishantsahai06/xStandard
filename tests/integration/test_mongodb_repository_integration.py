"""Real-MongoDB integration tests for ``MongoDBFaultModuleRepository``.

Every test hits a genuine MongoDB 7.0 instance running inside a
testcontainers-managed Docker container.  Collections are dropped
before and after each test via the ``mongo_repo`` fixture in conftest.

Sections
────────
A. Save (trusted + review)
B. Get (found / missing / wrong collection)
C. List by collection (ordering, pagination, filtering)
D. Count
E. Delete (existing, missing/idempotent, cross-collection isolation)
F. Upsert / overwrite behaviour
G. ensure_indexes (idempotent, creates expected indexes)
H. Document shape / round-trip fidelity
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.mongodb_repository import (
    MongoDBFaultModuleRepository,
)
from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.ports import FaultModuleRepositoryPort
from fault_mapper.domain.value_objects import PersistenceEnvelope

from tests.fixtures.persistence_fixtures import make_envelope


# ═══════════════════════════════════════════════════════════════════════
#  A. SAVE
# ═══════════════════════════════════════════════════════════════════════


class TestSave:
    """Write envelopes to the real MongoDB instance."""

    def test_save_trusted_returns_success(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        env = make_envelope(record_id="INT-T1", collection="trusted")
        result = mongo_repo.save(env)
        assert result.success is True
        assert result.record_id == "INT-T1"
        assert result.collection == "trusted"
        assert result.stored_at is not None

    def test_save_review_returns_success(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        env = make_envelope(
            record_id="INT-R1",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
        )
        result = mongo_repo.save(env)
        assert result.success is True
        assert result.collection == "review"

    def test_save_makes_document_retrievable(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        env = make_envelope(record_id="INT-T2", collection="trusted")
        mongo_repo.save(env)

        retrieved = mongo_repo.get("INT-T2", "trusted")
        assert retrieved is not None
        assert retrieved.record_id == "INT-T2"
        assert retrieved.collection == "trusted"

    def test_save_to_both_collections(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(record_id="INT-B1", collection="trusted"))
        mongo_repo.save(make_envelope(
            record_id="INT-B2",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
        ))
        assert mongo_repo.count("trusted") == 1
        assert mongo_repo.count("review") == 1

    def test_same_record_id_different_collections_coexist(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """Same record_id in different collections are separate docs."""
        mongo_repo.save(make_envelope(record_id="INT-DUP", collection="trusted"))
        mongo_repo.save(make_envelope(
            record_id="INT-DUP",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))
        assert mongo_repo.count("trusted") == 1
        assert mongo_repo.count("review") == 1
        assert mongo_repo.get("INT-DUP", "trusted") is not None
        assert mongo_repo.get("INT-DUP", "review") is not None


# ═══════════════════════════════════════════════════════════════════════
#  B. GET
# ═══════════════════════════════════════════════════════════════════════


class TestGet:
    """Read single envelopes back from the real MongoDB instance."""

    def test_get_existing_returns_envelope(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        env = make_envelope(
            record_id="INT-G1",
            collection="trusted",
            mapping_version="5.0.0",
        )
        mongo_repo.save(env)

        got = mongo_repo.get("INT-G1", "trusted")
        assert got is not None
        assert got.record_id == "INT-G1"
        assert got.mapping_version == "5.0.0"

    def test_get_missing_returns_none(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        assert mongo_repo.get("NONEXISTENT", "trusted") is None

    def test_get_wrong_collection_returns_none(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(record_id="INT-G2", collection="trusted"))
        assert mongo_repo.get("INT-G2", "review") is None

    def test_get_preserves_all_metadata(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        env = make_envelope(
            record_id="INT-META",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
            review_status=ReviewStatus.NOT_REVIEWED,
            mapping_version="2.3.1",
            stored_at="2026-04-13T10:00:00+00:00",
        )
        mongo_repo.save(env)

        got = mongo_repo.get("INT-META", "review")
        assert got is not None
        assert got.validation_status is ValidationStatus.REVIEW_REQUIRED
        assert got.review_status is ReviewStatus.NOT_REVIEWED
        assert got.mapping_version == "2.3.1"
        assert got.stored_at == "2026-04-13T10:00:00+00:00"


# ═══════════════════════════════════════════════════════════════════════
#  C. LIST_BY_COLLECTION
# ═══════════════════════════════════════════════════════════════════════


class TestListByCollection:
    """List and pagination against the real MongoDB instance."""

    def test_empty_collection_returns_empty(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        assert mongo_repo.list_by_collection("trusted") == []

    def test_returns_only_matching_collection(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(record_id="L-T1", collection="trusted"))
        mongo_repo.save(make_envelope(record_id="L-T2", collection="trusted"))
        mongo_repo.save(make_envelope(
            record_id="L-R1",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))

        trusted = mongo_repo.list_by_collection("trusted")
        assert len(trusted) == 2
        assert all(e.collection == "trusted" for e in trusted)

    def test_sorted_by_stored_at_descending(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(
            record_id="L-OLD",
            stored_at="2026-01-01T00:00:00+00:00",
        ))
        mongo_repo.save(make_envelope(
            record_id="L-NEW",
            stored_at="2026-06-01T00:00:00+00:00",
        ))

        listed = mongo_repo.list_by_collection("trusted")
        assert listed[0].record_id == "L-NEW"
        assert listed[1].record_id == "L-OLD"

    def test_pagination_limit(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        for i in range(5):
            mongo_repo.save(make_envelope(
                record_id=f"L-P{i}",
                stored_at=f"2026-01-01T{i:02d}:00:00+00:00",
            ))
        page = mongo_repo.list_by_collection("trusted", limit=2)
        assert len(page) == 2

    def test_pagination_offset(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        for i in range(5):
            mongo_repo.save(make_envelope(
                record_id=f"L-O{i}",
                stored_at=f"2026-01-01T{i:02d}:00:00+00:00",
            ))
        all_envs = mongo_repo.list_by_collection("trusted", limit=100)
        page2 = mongo_repo.list_by_collection("trusted", limit=2, offset=2)
        assert len(page2) == 2
        assert page2[0].record_id == all_envs[2].record_id


# ═══════════════════════════════════════════════════════════════════════
#  D. COUNT
# ═══════════════════════════════════════════════════════════════════════


class TestCount:
    """Count documents in the real MongoDB instance."""

    def test_empty_collection(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        assert mongo_repo.count("trusted") == 0

    def test_count_after_saves(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        for i in range(4):
            mongo_repo.save(make_envelope(record_id=f"C-{i}"))
        assert mongo_repo.count("trusted") == 4

    def test_count_per_collection(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(record_id="C-T1", collection="trusted"))
        mongo_repo.save(make_envelope(
            record_id="C-R1",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))
        mongo_repo.save(make_envelope(
            record_id="C-R2",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))
        assert mongo_repo.count("trusted") == 1
        assert mongo_repo.count("review") == 2


# ═══════════════════════════════════════════════════════════════════════
#  E. DELETE
# ═══════════════════════════════════════════════════════════════════════


class TestDelete:
    """Delete operations against the real MongoDB instance."""

    def test_delete_existing_returns_success(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(
            record_id="D-1",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))
        result = mongo_repo.delete("D-1", "review")
        assert result.success is True
        assert result.record_id == "D-1"

    def test_delete_removes_from_collection(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(
            record_id="D-2",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))
        mongo_repo.delete("D-2", "review")
        assert mongo_repo.get("D-2", "review") is None
        assert mongo_repo.count("review") == 0

    def test_delete_nonexistent_returns_success(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """Idempotent delete — missing key is not an error."""
        result = mongo_repo.delete("NOPE", "review")
        assert result.success is True

    def test_delete_does_not_affect_other_collections(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(record_id="D-X", collection="trusted"))
        mongo_repo.save(make_envelope(
            record_id="D-X",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))

        mongo_repo.delete("D-X", "review")

        assert mongo_repo.get("D-X", "trusted") is not None
        assert mongo_repo.get("D-X", "review") is None

    def test_delete_updates_count(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        mongo_repo.save(make_envelope(
            record_id="D-C1",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))
        mongo_repo.save(make_envelope(
            record_id="D-C2",
            collection="review",
            validation_status=ValidationStatus.REVIEW_REQUIRED,
        ))
        assert mongo_repo.count("review") == 2

        mongo_repo.delete("D-C1", "review")
        assert mongo_repo.count("review") == 1


# ═══════════════════════════════════════════════════════════════════════
#  F. UPSERT / OVERWRITE
# ═══════════════════════════════════════════════════════════════════════


class TestUpsert:
    """Verify replace_one upsert behaviour in the real MongoDB instance."""

    def test_upsert_replaces_existing(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        env1 = make_envelope(record_id="U-1", mapping_version="1.0.0")
        env2 = make_envelope(record_id="U-1", mapping_version="2.0.0")
        mongo_repo.save(env1)
        mongo_repo.save(env2)

        got = mongo_repo.get("U-1", "trusted")
        assert got is not None
        assert got.mapping_version == "2.0.0"
        assert mongo_repo.count("trusted") == 1

    def test_upsert_preserves_new_document_payload(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        doc_v1 = {"recordId": "U-2", "version": "old"}
        doc_v2 = {"recordId": "U-2", "version": "new", "extra": True}

        mongo_repo.save(make_envelope(record_id="U-2", document=doc_v1))
        mongo_repo.save(make_envelope(record_id="U-2", document=doc_v2))

        got = mongo_repo.get("U-2", "trusted")
        assert got is not None
        assert got.document["version"] == "new"
        assert got.document["extra"] is True


# ═══════════════════════════════════════════════════════════════════════
#  G. ENSURE_INDEXES
# ═══════════════════════════════════════════════════════════════════════


class TestEnsureIndexes:
    """ensure_indexes is idempotent and creates expected indexes."""

    def test_ensure_indexes_idempotent(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """Calling twice does not raise."""
        mongo_repo.ensure_indexes()
        mongo_repo.ensure_indexes()

    def test_indexes_exist_after_creation(
        self,
        mongo_repo: MongoDBFaultModuleRepository,
        mongo_client,
        mongo_config,
    ) -> None:
        """Verify expected index keys are present on both collections."""
        mongo_repo.ensure_indexes()

        db = mongo_client[mongo_config.database_name]
        for coll_name in (
            mongo_config.trusted_collection,
            mongo_config.review_collection,
        ):
            coll = db[coll_name]
            index_info = coll.index_information()
            index_keys = {
                key
                for idx in index_info.values()
                for key, _ in idx["key"]
            }
            assert "record_id" in index_keys
            assert "stored_at" in index_keys
            assert "validation_status" in index_keys


# ═══════════════════════════════════════════════════════════════════════
#  H. DOCUMENT SHAPE / ROUND-TRIP FIDELITY
# ═══════════════════════════════════════════════════════════════════════


class TestDocumentShape:
    """Verify the raw MongoDB document has the expected structure."""

    def test_raw_document_has_expected_keys(
        self,
        mongo_repo: MongoDBFaultModuleRepository,
        mongo_client,
        mongo_config,
    ) -> None:
        env = make_envelope(record_id="SH-1")
        mongo_repo.save(env)

        db = mongo_client[mongo_config.database_name]
        coll = db[mongo_config.trusted_collection]
        doc = coll.find_one({"_id": "SH-1"})

        assert doc is not None
        expected_keys = {
            "_id", "record_id", "collection", "validation_status",
            "review_status", "mapping_version", "stored_at", "document",
        }
        assert expected_keys == set(doc.keys())

    def test_enum_values_stored_as_strings(
        self,
        mongo_repo: MongoDBFaultModuleRepository,
        mongo_client,
        mongo_config,
    ) -> None:
        env = make_envelope(record_id="SH-2")
        mongo_repo.save(env)

        db = mongo_client[mongo_config.database_name]
        coll = db[mongo_config.trusted_collection]
        doc = coll.find_one({"_id": "SH-2"})

        assert doc is not None
        assert isinstance(doc["validation_status"], str)
        assert doc["validation_status"] == "approved"
        assert isinstance(doc["review_status"], str)
        assert doc["review_status"] == "approved"

    def test_nested_document_survives_round_trip(
        self, mongo_repo: MongoDBFaultModuleRepository,
    ) -> None:
        """The ``document`` dict (serialised module) is preserved."""
        nested = {
            "recordId": "SH-3",
            "recordType": "S1000D_FaultDataModule",
            "header": {"dmCode": {"modelIdentCode": "TESTAC"}},
            "content": {"faultReporting": {"entries": []}},
        }
        env = make_envelope(record_id="SH-3", document=nested)
        mongo_repo.save(env)

        got = mongo_repo.get("SH-3", "trusted")
        assert got is not None
        assert got.document == nested
        assert got.document["header"]["dmCode"]["modelIdentCode"] == "TESTAC"

    def test_protocol_compliance(self) -> None:
        """MongoDBFaultModuleRepository satisfies FaultModuleRepositoryPort."""
        assert issubclass(
            MongoDBFaultModuleRepository,
            type,
        ) or isinstance(
            MongoDBFaultModuleRepository,
            type,
        )
        # Runtime protocol check
        from fault_mapper.infrastructure.config import MongoConfig as MC

        repo = MongoDBFaultModuleRepository.__new__(
            MongoDBFaultModuleRepository,
        )
        assert isinstance(repo, FaultModuleRepositoryPort)
