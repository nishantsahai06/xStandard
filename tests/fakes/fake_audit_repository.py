"""Fake audit repository — test double for ``AuditRepositoryPort``.

Delegates to ``InMemoryAuditRepository`` and adds test-inspection
hooks (``fail_on_append``, ``append_calls``).
"""

from __future__ import annotations

from fault_mapper.adapters.secondary.in_memory_audit_repository import (
    InMemoryAuditRepository,
)
from fault_mapper.domain.value_objects import AuditEntry


class FakeAuditRepository:
    """Test-double audit repository with inspection hooks.

    By default, delegates to ``InMemoryAuditRepository``.
    Set ``fail_on_append = True`` to simulate write failures.
    """

    def __init__(self) -> None:
        self._inner = InMemoryAuditRepository()
        self.append_calls: list[AuditEntry] = []
        self.fail_on_append: bool = False
        self.fail_error_message: str = "Simulated audit repository failure"

    # ── Write ────────────────────────────────────────────────────

    def append(self, entry: AuditEntry) -> None:
        """Record the call, then delegate or fail."""
        self.append_calls.append(entry)
        if self.fail_on_append:
            raise RuntimeError(self.fail_error_message)
        self._inner.append(entry)

    # ── Read ─────────────────────────────────────────────────────

    def list_by_record_id(self, record_id: str) -> list[AuditEntry]:
        return self._inner.list_by_record_id(record_id)

    # ── Test helpers ─────────────────────────────────────────────

    def clear(self) -> None:
        """Reset all state."""
        self._inner.clear()
        self.append_calls.clear()
        self.fail_on_append = False

    @property
    def all_entries(self) -> list[AuditEntry]:
        """All entries currently stored."""
        return self._inner.all_entries
