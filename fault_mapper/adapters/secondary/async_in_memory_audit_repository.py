"""Async in-memory audit repository — implements ``AsyncAuditRepositoryPort``."""

from __future__ import annotations

from fault_mapper.domain.value_objects import AuditEntry


class AsyncInMemoryAuditRepository:
    """Async adapter for audit storage backed by a plain list."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    async def append(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    async def list_by_record_id(self, record_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.record_id == record_id]

    # ── Test helpers ─────────────────────────────────────────────

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
