"""Async fake repository — test double for ``AsyncFaultModuleRepositoryPort``.

Delegates to ``AsyncInMemoryFaultModuleRepository`` and adds
test-inspection hooks (``save_calls``, ``fail_on_save``, ``fail_on_delete``).
"""

from __future__ import annotations

from fault_mapper.adapters.secondary.async_in_memory_repository import (
    AsyncInMemoryFaultModuleRepository,
)
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)


class AsyncFakeFaultModuleRepository:
    """Async test-double repository with inspection hooks."""

    def __init__(self) -> None:
        self._inner = AsyncInMemoryFaultModuleRepository()
        self.save_calls: list[PersistenceEnvelope] = []
        self.delete_calls: list[tuple[str, str]] = []
        self.fail_on_save: bool = False
        self.fail_on_delete: bool = False
        self.fail_error_message: str = "Simulated repository failure"

    async def save(self, envelope: PersistenceEnvelope) -> PersistenceResult:
        self.save_calls.append(envelope)
        if self.fail_on_save:
            return PersistenceResult(
                success=False,
                record_id=envelope.record_id,
                collection=envelope.collection,
                error=self.fail_error_message,
            )
        return await self._inner.save(envelope)

    async def get(
        self, record_id: str, collection: str,
    ) -> PersistenceEnvelope | None:
        return await self._inner.get(record_id, collection)

    async def list_by_collection(
        self, collection: str, *, limit: int = 100, offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return await self._inner.list_by_collection(
            collection, limit=limit, offset=offset,
        )

    async def count(self, collection: str) -> int:
        return await self._inner.count(collection)

    async def list_record_ids(self, collection: str) -> list[str]:
        return await self._inner.list_record_ids(collection)

    async def delete(
        self, record_id: str, collection: str,
    ) -> PersistenceResult:
        self.delete_calls.append((record_id, collection))
        if self.fail_on_delete:
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection=collection,
                error=self.fail_error_message,
            )
        return await self._inner.delete(record_id, collection)

    def clear(self) -> None:
        self._inner.clear()
        self.save_calls.clear()
        self.delete_calls.clear()
        self.fail_on_save = False
        self.fail_on_delete = False

    @property
    def saved_envelopes(self) -> list[PersistenceEnvelope]:
        return self._inner.all_envelopes
