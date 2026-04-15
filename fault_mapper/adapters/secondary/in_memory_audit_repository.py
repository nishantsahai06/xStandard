"""In-memory audit repository — implements ``AuditRepositoryPort``.

Stores audit entries in a plain Python list.  Suitable for testing
and lightweight deployments where durable audit storage is not required.

Thread safety: not guaranteed — acceptable for tests and single-threaded
dev servers.
"""

from __future__ import annotations

from fault_mapper.domain.value_objects import AuditEntry


class InMemoryAuditRepository:
    """In-memory implementation of ``AuditRepositoryPort``.

    Entries are stored in insertion order and retrievable by
    ``record_id``.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    # ── Write ────────────────────────────────────────────────────

    def append(self, entry: AuditEntry) -> None:
        """Append an audit entry to the in-memory store."""
        self._entries.append(entry)

    # ── Read ─────────────────────────────────────────────────────

    def list_by_record_id(self, record_id: str) -> list[AuditEntry]:
        """Return entries for a record in chronological order."""
        return [e for e in self._entries if e.record_id == record_id]

    # ── Test helpers ─────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all stored entries.  Useful in test teardown."""
        self._entries.clear()

    @property
    def all_entries(self) -> list[AuditEntry]:
        """Return all stored entries (all records)."""
        return list(self._entries)
