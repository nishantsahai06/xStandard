"""Async in-memory repository — implements ``AsyncFaultModuleRepositoryPort``.

Wraps the existing ``InMemoryFaultModuleRepository`` with async
methods.  All I/O is actually in-memory so there's no real blocking,
but the async interface lets services written against the async port
run without change against both real (Motor) and test adapters.
"""

from __future__ import annotations

from fault_mapper.adapters.secondary.in_memory_repository import (
    InMemoryFaultModuleRepository,
)
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)


class AsyncInMemoryFaultModuleRepository:
    """Async adapter backed by the sync ``InMemoryFaultModuleRepository``."""

    def __init__(self) -> None:
        self._inner = InMemoryFaultModuleRepository()

    async def save(self, envelope: PersistenceEnvelope) -> PersistenceResult:
        return self._inner.save(envelope)

    async def get(
        self, record_id: str, collection: str,
    ) -> PersistenceEnvelope | None:
        return self._inner.get(record_id, collection)

    async def list_by_collection(
        self, collection: str, *, limit: int = 100, offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return self._inner.list_by_collection(
            collection, limit=limit, offset=offset,
        )

    async def count(self, collection: str) -> int:
        return self._inner.count(collection)

    async def list_record_ids(self, collection: str) -> list[str]:
        return self._inner.list_record_ids(collection)

    async def delete(
        self, record_id: str, collection: str,
    ) -> PersistenceResult:
        return self._inner.delete(record_id, collection)

    # ── Test helpers ─────────────────────────────────────────────

    def clear(self) -> None:
        self._inner.clear()

    @property
    def all_envelopes(self) -> list[PersistenceEnvelope]:
        return self._inner.all_envelopes
