"""MongoDB adapter — implements ``FaultModuleRepositoryPort``.

This is a **secondary adapter** that bridges the domain's persistence
port to a real MongoDB instance via ``pymongo``.

Collection mapping
──────────────────
The adapter resolves the logical ``collection`` name in each envelope
to a physical MongoDB collection within the configured database:

    ``"trusted"``  → ``MongoConfig.trusted_collection``
    ``"review"``   → ``MongoConfig.review_collection``

Document shape
──────────────
Each stored document has the structure::

    {
        "_id":                <record_id>,
        "record_id":          <record_id>,
        "collection":         <logical collection name>,
        "validation_status":  <enum value>,
        "review_status":      <enum value>,
        "mapping_version":    <str | null>,
        "stored_at":          <ISO 8601>,
        "document":           { … serialised module … }
    }

The ``_id`` is set to ``record_id`` so upserts are natural
``replace_one(filter={"_id": record_id}, …, upsert=True)``.

Dependency
──────────
Requires ``pymongo>=4.0``.  Import is deferred inside methods so
that the rest of the codebase is importable without pymongo installed
(e.g. during testing with the in-memory adapter).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)
from fault_mapper.infrastructure.config import MongoConfig


class MongoDBFaultModuleRepository:
    """MongoDB-backed implementation of ``FaultModuleRepositoryPort``.

    Parameters
    ----------
    config : MongoConfig
        Connection URI, database name, collection names.
    client : Any | None
        An existing ``pymongo.MongoClient`` instance.  If ``None``,
        one is created from ``config.connection_uri``.
    """

    def __init__(
        self,
        config: MongoConfig,
        client: Any | None = None,
    ) -> None:
        self._config = config

        if client is not None:
            self._client = client
        else:
            try:
                from pymongo import MongoClient  # type: ignore[import-untyped]
                self._client = MongoClient(config.connection_uri)
            except ImportError as exc:
                raise ImportError(
                    "pymongo is required for MongoDBFaultModuleRepository. "
                    "Install with: pip install pymongo"
                ) from exc

        self._db = self._client[config.database_name]

        # Logical name → physical collection mapping
        self._collection_map: dict[str, str] = {
            "trusted": config.trusted_collection,
            "review": config.review_collection,
        }

    # ── Helpers ──────────────────────────────────────────────────

    def _resolve_collection(self, logical_name: str) -> Any:
        """Return the pymongo Collection for a logical name."""
        physical = self._collection_map.get(logical_name, logical_name)
        return self._db[physical]

    @staticmethod
    def _envelope_to_doc(envelope: PersistenceEnvelope) -> dict[str, Any]:
        """Convert an envelope to the MongoDB document shape."""
        return {
            "_id": envelope.record_id,
            "record_id": envelope.record_id,
            "collection": envelope.collection,
            "validation_status": envelope.validation_status.value,
            "review_status": envelope.review_status.value,
            "mapping_version": envelope.mapping_version,
            "stored_at": envelope.stored_at,
            "document": envelope.document,
        }

    @staticmethod
    def _doc_to_envelope(doc: dict[str, Any]) -> PersistenceEnvelope:
        """Reconstruct an envelope from a stored MongoDB document."""
        return PersistenceEnvelope(
            record_id=doc["record_id"],
            collection=doc["collection"],
            document=doc["document"],
            validation_status=ValidationStatus(doc["validation_status"]),
            review_status=ReviewStatus(doc["review_status"]),
            mapping_version=doc.get("mapping_version"),
            stored_at=doc.get("stored_at"),
        )

    # ── Write ────────────────────────────────────────────────────

    def save(self, envelope: PersistenceEnvelope) -> PersistenceResult:
        """Upsert a module envelope into MongoDB."""
        coll = self._resolve_collection(envelope.collection)
        mongo_doc = self._envelope_to_doc(envelope)

        try:
            coll.replace_one(
                {"_id": envelope.record_id},
                mongo_doc,
                upsert=True,
            )
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=envelope.record_id,
                collection=envelope.collection,
                error=f"MongoDB write failed: {exc}",
            )

        now = datetime.now(timezone.utc).isoformat()
        return PersistenceResult(
            success=True,
            record_id=envelope.record_id,
            collection=envelope.collection,
            stored_at=now,
        )

    # ── Read ─────────────────────────────────────────────────────

    def get(
        self,
        record_id: str,
        collection: str,
    ) -> PersistenceEnvelope | None:
        """Retrieve an envelope by record ID from the specified collection."""
        coll = self._resolve_collection(collection)
        doc = coll.find_one({"_id": record_id})
        if doc is None:
            return None
        return self._doc_to_envelope(doc)

    def list_by_collection(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        """List envelopes with pagination, ordered by stored_at desc."""
        coll = self._resolve_collection(collection)
        cursor = (
            coll.find()
            .sort("stored_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return [self._doc_to_envelope(doc) for doc in cursor]

    def count(self, collection: str) -> int:
        """Count documents in the specified collection."""
        coll = self._resolve_collection(collection)
        return coll.count_documents({})

    def list_record_ids(self, collection: str) -> list[str]:
        """Return all record IDs in the specified collection."""
        coll = self._resolve_collection(collection)
        return [
            doc["_id"]
            for doc in coll.find({}, {"_id": 1})
        ]

    def delete(
        self,
        record_id: str,
        collection: str,
    ) -> PersistenceResult:
        """Remove a document from the specified collection.

        Returns ``success=True`` even if the document did not exist
        (idempotent delete).  Returns ``success=False`` only on a
        backend / network error.
        """
        coll = self._resolve_collection(collection)
        try:
            coll.delete_one({"_id": record_id})
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection=collection,
                error=f"MongoDB delete failed: {exc}",
            )
        return PersistenceResult(
            success=True,
            record_id=record_id,
            collection=collection,
        )

    # ── Lifecycle ────────────────────────────────────────────────

    def ensure_indexes(self) -> None:
        """Create recommended indexes on all managed collections.

        Call once at startup — idempotent.
        """
        for logical_name in self._collection_map:
            coll = self._resolve_collection(logical_name)
            coll.create_index("record_id", unique=True)
            coll.create_index("stored_at")
            coll.create_index("validation_status")
