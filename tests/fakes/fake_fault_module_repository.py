"""Fake repository — test double for ``FaultModuleRepositoryPort``.

Delegates to ``InMemoryFaultModuleRepository`` for storage and adds
test-inspection hooks (e.g. ``saved_envelopes``, ``save_calls``,
``fail_on_save``).
"""

from __future__ import annotations

from fault_mapper.adapters.secondary.in_memory_repository import (
    InMemoryFaultModuleRepository,
)
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)


class FakeFaultModuleRepository:
    """Test-double repository with inspection hooks.

    By default, delegates to ``InMemoryFaultModuleRepository``.
    Set ``fail_on_save = True`` to simulate write failures.
    Set ``fail_on_delete = True`` to simulate delete failures.
    """

    def __init__(self) -> None:
        self._inner = InMemoryFaultModuleRepository()
        self.save_calls: list[PersistenceEnvelope] = []
        self.delete_calls: list[tuple[str, str]] = []
        self.fail_on_save: bool = False
        self.fail_on_delete: bool = False
        self.fail_error_message: str = "Simulated repository failure"

    # ── Write ────────────────────────────────────────────────────

    def save(self, envelope: PersistenceEnvelope) -> PersistenceResult:
        """Record the call, then delegate or fail."""
        self.save_calls.append(envelope)
        if self.fail_on_save:
            return PersistenceResult(
                success=False,
                record_id=envelope.record_id,
                collection=envelope.collection,
                error=self.fail_error_message,
            )
        return self._inner.save(envelope)

    # ── Read ─────────────────────────────────────────────────────

    def get(
        self,
        record_id: str,
        collection: str,
    ) -> PersistenceEnvelope | None:
        return self._inner.get(record_id, collection)

    def list_by_collection(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return self._inner.list_by_collection(
            collection, limit=limit, offset=offset,
        )

    def count(self, collection: str) -> int:
        return self._inner.count(collection)

    def list_record_ids(self, collection: str) -> list[str]:
        return self._inner.list_record_ids(collection)

    # ── Delete ───────────────────────────────────────────────────

    def delete(
        self,
        record_id: str,
        collection: str,
    ) -> PersistenceResult:
        """Record the call, then delegate or fail."""
        self.delete_calls.append((record_id, collection))
        if self.fail_on_delete:
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection=collection,
                error=self.fail_error_message,
            )
        return self._inner.delete(record_id, collection)

    # ── Test helpers ─────────────────────────────────────────────

    def clear(self) -> None:
        """Reset all state."""
        self._inner.clear()
        self.save_calls.clear()
        self.delete_calls.clear()
        self.fail_on_save = False
        self.fail_on_delete = False

    @property
    def saved_envelopes(self) -> list[PersistenceEnvelope]:
        """All envelopes currently stored (all collections)."""
        return self._inner.all_envelopes
