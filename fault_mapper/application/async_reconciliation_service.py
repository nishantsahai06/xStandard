"""Async reconciliation / sweep service — async counterpart of
``FaultModuleReconciliationService``.

Same sweep algorithm (detect orphaned review entries, safety checks,
optional cleanup), but delegates to ``AsyncFaultModuleRepositoryPort``
and optionally ``AsyncAuditRepositoryPort`` via ``await``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fault_mapper.domain.enums import (
    AuditEventType,
    ReconciliationOutcome,
    ValidationStatus,
)
from fault_mapper.domain.ports import AsyncFaultModuleRepositoryPort
from fault_mapper.domain.value_objects import (
    AuditEntry,
    PersistenceEnvelope,
    ReconciliationDetail,
    ReconciliationReport,
)

if TYPE_CHECKING:
    from fault_mapper.domain.ports import AsyncAuditRepositoryPort


# Trusted-equivalent statuses: the trusted record is authoritative
_TRUSTED_AUTHORITATIVE: frozenset[ValidationStatus] = frozenset({
    ValidationStatus.APPROVED,
    ValidationStatus.STORED,
})

# Review statuses that indicate the item was already promoted
_REVIEW_ORPHAN_STATUSES: frozenset[ValidationStatus] = frozenset({
    ValidationStatus.APPROVED,
})


class AsyncFaultModuleReconciliationService:
    """Async application service that detects and cleans orphaned review entries."""

    def __init__(
        self,
        repository: AsyncFaultModuleRepositoryPort,
        audit_repo: AsyncAuditRepositoryPort | None = None,
    ) -> None:
        self._repo = repository
        self._audit_repo = audit_repo

    # ── Public API ───────────────────────────────────────────────

    async def sweep(
        self,
        *,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> ReconciliationReport:
        """Run a single async reconciliation sweep."""
        review_ids = await self._repo.list_record_ids("review")
        if limit is not None:
            review_ids = review_ids[:limit]

        total_scanned = len(review_ids)

        trusted_ids = set(await self._repo.list_record_ids("trusted"))

        duplicate_ids = [
            rid for rid in review_ids if rid in trusted_ids
        ]

        details: list[ReconciliationDetail] = []
        cleaned = 0
        skipped = 0
        errors = 0

        for record_id in duplicate_ids:
            detail = await self._process_duplicate(
                record_id, dry_run=dry_run,
            )
            details.append(detail)
            if detail.outcome == ReconciliationOutcome.CLEANED:
                cleaned += 1
            elif detail.outcome == ReconciliationOutcome.SKIPPED:
                skipped += 1
            else:
                errors += 1

        return ReconciliationReport(
            total_review_scanned=total_scanned,
            duplicates_found=len(duplicate_ids),
            duplicates_cleaned=cleaned,
            duplicates_skipped=skipped,
            errors=errors,
            dry_run=dry_run,
            details=details,
        )

    async def find_orphaned_review_ids(self) -> list[str]:
        """List record IDs that exist in both review and trusted."""
        review_ids = await self._repo.list_record_ids("review")
        trusted_ids = set(await self._repo.list_record_ids("trusted"))
        return [rid for rid in review_ids if rid in trusted_ids]

    # ── Private helpers ──────────────────────────────────────────

    async def _process_duplicate(
        self,
        record_id: str,
        *,
        dry_run: bool,
    ) -> ReconciliationDetail:
        """Evaluate and optionally clean a single duplicate."""
        trusted_env = await self._repo.get(record_id, "trusted")
        review_env = await self._repo.get(record_id, "review")

        if trusted_env is None:
            return ReconciliationDetail(
                record_id=record_id,
                outcome=ReconciliationOutcome.SKIPPED,
                reason="Trusted record disappeared during sweep",
            )
        if review_env is None:
            return ReconciliationDetail(
                record_id=record_id,
                outcome=ReconciliationOutcome.SKIPPED,
                reason="Review record disappeared during sweep",
            )

        if trusted_env.validation_status not in _TRUSTED_AUTHORITATIVE:
            return await self._skip(
                record_id,
                f"Trusted record has non-authoritative status: "
                f"{trusted_env.validation_status.value}",
            )

        if review_env.validation_status not in _REVIEW_ORPHAN_STATUSES:
            return await self._skip(
                record_id,
                f"Review record has unexpected status: "
                f"{review_env.validation_status.value} "
                f"(expected one of: "
                f"{', '.join(s.value for s in _REVIEW_ORPHAN_STATUSES)})",
            )

        if not self._documents_compatible(trusted_env, review_env):
            return await self._skip(
                record_id,
                "Conflicting document content between trusted and "
                "review records",
            )

        if dry_run:
            await self._record_audit(
                record_id=record_id,
                event_type=AuditEventType.RECONCILIATION_CLEANED,
                reason="Dry-run: would delete orphaned review entry",
            )
            return ReconciliationDetail(
                record_id=record_id,
                outcome=ReconciliationOutcome.CLEANED,
                reason="Dry-run: would delete orphaned review entry",
            )

        try:
            result = await self._repo.delete(record_id, "review")
        except Exception as exc:  # noqa: BLE001
            return ReconciliationDetail(
                record_id=record_id,
                outcome=ReconciliationOutcome.ERROR,
                reason=f"Delete failed: {exc}",
            )

        if not result.success:
            return ReconciliationDetail(
                record_id=record_id,
                outcome=ReconciliationOutcome.ERROR,
                reason=f"Delete failed: {result.error}",
            )

        await self._record_audit(
            record_id=record_id,
            event_type=AuditEventType.RECONCILIATION_CLEANED,
            reason="Orphaned review entry deleted by reconciliation sweep",
        )

        return ReconciliationDetail(
            record_id=record_id,
            outcome=ReconciliationOutcome.CLEANED,
            reason="Orphaned review entry deleted",
        )

    @staticmethod
    def _documents_compatible(
        trusted: PersistenceEnvelope,
        review: PersistenceEnvelope,
    ) -> bool:
        """Check whether trusted and review documents are compatible."""
        t_doc = trusted.document
        r_doc = review.document

        t_rid = t_doc.get("recordId")
        r_rid = r_doc.get("recordId")
        if t_rid is not None and r_rid is not None and t_rid != r_rid:
            return False

        t_type = t_doc.get("recordType")
        r_type = r_doc.get("recordType")
        if t_type is not None and r_type is not None and t_type != r_type:
            return False

        return True

    async def _skip(
        self,
        record_id: str,
        reason: str,
    ) -> ReconciliationDetail:
        """Build a SKIPPED detail and optionally record an audit entry."""
        await self._record_audit(
            record_id=record_id,
            event_type=AuditEventType.RECONCILIATION_SKIPPED,
            reason=reason,
        )
        return ReconciliationDetail(
            record_id=record_id,
            outcome=ReconciliationOutcome.SKIPPED,
            reason=reason,
        )

    async def _record_audit(
        self,
        *,
        record_id: str,
        event_type: AuditEventType,
        reason: str,
    ) -> None:
        """Write an audit entry (best-effort — swallows exceptions)."""
        if self._audit_repo is None:
            return
        try:
            now = datetime.now(timezone.utc).isoformat()
            entry = AuditEntry(
                record_id=record_id,
                event_type=event_type,
                reason=reason,
                timestamp=now,
                performed_by="reconciliation-sweep",
                collection="review",
            )
            await self._audit_repo.append(entry)
        except Exception:  # noqa: BLE001
            pass
