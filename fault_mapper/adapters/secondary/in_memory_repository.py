"""In-memory adapter — implements ``FaultModuleRepositoryPort``.

Zero-dependency implementation for development, testing, and
lightweight deployments that do not require durable storage.

Data is held in plain Python dicts keyed by ``(collection, record_id)``
and lost when the process exits.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)


class InMemoryFaultModuleRepository:
    """In-memory implementation of ``FaultModuleRepositoryPort``.

    Stores envelopes in a dict keyed by ``(collection, record_id)``.
    Thread-safe only if callers serialise access externally (acceptable
    for tests and single-threaded dev servers).
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], PersistenceEnvelope] = {}

    # ── Write ────────────────────────────────────────────────────

    def save(self, envelope: PersistenceEnvelope) -> PersistenceResult:
        """Upsert an envelope into the in-memory store."""
        key = (envelope.collection, envelope.record_id)
        self._store[key] = envelope
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
        """Retrieve an envelope by (collection, record_id)."""
        return self._store.get((collection, record_id))

    def list_by_collection(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        """List envelopes for a collection with pagination.

        Ordered by ``stored_at`` descending (newest first).
        """
        envelopes = [
            env for (coll, _rid), env in self._store.items()
            if coll == collection
        ]
        # Sort by stored_at descending (None sorts last)
        envelopes.sort(
            key=lambda e: e.stored_at or "",
            reverse=True,
        )
        return envelopes[offset: offset + limit]

    def count(self, collection: str) -> int:
        """Count envelopes in the specified collection."""
        return sum(
            1 for (coll, _) in self._store if coll == collection
        )

    def list_record_ids(self, collection: str) -> list[str]:
        """Return all record IDs in the specified collection."""
        return [
            rid for (coll, rid) in self._store if coll == collection
        ]

    # ── Delete ───────────────────────────────────────────────────

    def delete(
        self,
        record_id: str,
        collection: str,
    ) -> PersistenceResult:
        """Remove an envelope from the in-memory store.

        Returns ``success=True`` even if the key did not exist
        (idempotent delete).
        """
        key = (collection, record_id)
        self._store.pop(key, None)
        return PersistenceResult(
            success=True,
            record_id=record_id,
            collection=collection,
        )

    # ── Test helpers ─────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all stored envelopes.  Useful in test teardown."""
        self._store.clear()

    @property
    def all_envelopes(self) -> list[PersistenceEnvelope]:
        """Return all stored envelopes (all collections)."""
        return list(self._store.values())
