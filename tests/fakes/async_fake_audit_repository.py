"""Async fake audit repository — test double for ``AsyncAuditRepositoryPort``.

Delegates to ``AsyncInMemoryAuditRepository`` and adds
test-inspection hooks (``fail_on_append``, ``append_calls``).
"""

from __future__ import annotations

from fault_mapper.adapters.secondary.async_in_memory_audit_repository import (
    AsyncInMemoryAuditRepository,
)
from fault_mapper.domain.value_objects import AuditEntry


class AsyncFakeAuditRepository:
    """Async test-double audit repository with inspection hooks."""

    def __init__(self) -> None:
        self._inner = AsyncInMemoryAuditRepository()
        self.append_calls: list[AuditEntry] = []
        self.fail_on_append: bool = False
        self.fail_error_message: str = "Simulated audit repository failure"

    async def append(self, entry: AuditEntry) -> None:
        self.append_calls.append(entry)
        if self.fail_on_append:
            raise RuntimeError(self.fail_error_message)
        await self._inner.append(entry)

    async def list_by_record_id(self, record_id: str) -> list[AuditEntry]:
        return await self._inner.list_by_record_id(record_id)

    def clear(self) -> None:
        self._inner.clear()
        self.append_calls.clear()
        self.fail_on_append = False

    @property
    def all_entries(self) -> list[AuditEntry]:
        return self._inner.entries
