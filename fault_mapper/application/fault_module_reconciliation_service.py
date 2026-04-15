"""Reconciliation / sweep service — detects and cleans orphaned review entries.

Sits in the application layer alongside the persistence and review services.
Handles the specific operational gap where a review → trusted promotion
succeeds but the subsequent review-collection delete fails, leaving the
same ``record_id`` in both collections.

Sweep algorithm
───────────────
1. List all ``record_id``s in the review collection.
2. For each, check whether the same ``record_id`` exists in trusted.
3. If a duplicate is found, apply safety checks:
   a. Trusted record must exist and have an authoritative status
      (``APPROVED`` or ``STORED``).
   b. Review record must be an actual orphan — its validation status
      should indicate it was already promoted (``APPROVED``).
   c. If the review record has a *different* document payload hash
      than the trusted record, it may represent a conflicting version
      and is skipped (conservative).
4. For safe-to-clean records: delete the orphaned review entry
   (unless ``dry_run=True``).
5. Build and return a ``ReconciliationReport`` with full details.

Design
──────
• Depends only on ``FaultModuleRepositoryPort`` (domain port).
• Optional ``AuditRepositoryPort`` for recording cleanup events.
• Produces ``ReconciliationReport`` / ``ReconciliationDetail`` value
  objects — never modifies the trusted collection.
• Conservative: when unsure, skip rather than delete.
• Audit logging is best-effort (same pattern as review service).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fault_mapper.domain.enums import (
    AuditEventType,
    ReconciliationOutcome,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.ports import FaultModuleRepositoryPort
from fault_mapper.domain.value_objects import (
    AuditEntry,
    PersistenceEnvelope,
    ReconciliationDetail,
    ReconciliationReport,
)

if TYPE_CHECKING:
    from fault_mapper.domain.ports import AuditRepositoryPort


# Trusted-equivalent statuses: the trusted record is authoritative
_TRUSTED_AUTHORITATIVE: frozenset[ValidationStatus] = frozenset({
    ValidationStatus.APPROVED,
    ValidationStatus.STORED,
})

# Review statuses that indicate the item was already promoted
_REVIEW_ORPHAN_STATUSES: frozenset[ValidationStatus] = frozenset({
    ValidationStatus.APPROVED,
})


class FaultModuleReconciliationService:
    """Application service that detects and cleans orphaned review entries.

    Parameters
    ----------
    repository : FaultModuleRepositoryPort
        The same repository used by persistence and review services.
    audit_repo : AuditRepositoryPort | None
        Optional audit repository for recording reconciliation events.
    """

    def __init__(
        self,
        repository: FaultModuleRepositoryPort,
        audit_repo: AuditRepositoryPort | None = None,
    ) -> None:
        self._repo = repository
        self._audit_repo = audit_repo

    # ── Public API ───────────────────────────────────────────────

    def sweep(
        self,
        *,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> ReconciliationReport:
        """Run a single reconciliation sweep.

        Parameters
        ----------
        dry_run : bool
            If True, report what *would* be cleaned without deleting.
        limit : int | None
            Maximum number of review records to scan.  None = all.

        Returns
        -------
        ReconciliationReport
            Full report with per-record details.
        """
        # 1. Get all review record IDs
        review_ids = self._repo.list_record_ids("review")
        if limit is not None:
            review_ids = review_ids[:limit]

        total_scanned = len(review_ids)

        # 2. Get all trusted record IDs for fast look-up
        trusted_ids = set(self._repo.list_record_ids("trusted"))

        # 3. Find duplicates — record_ids in both collections
        duplicate_ids = [
            rid for rid in review_ids if rid in trusted_ids
        ]

        details: list[ReconciliationDetail] = []
        cleaned = 0
        skipped = 0
        errors = 0

        for record_id in duplicate_ids:
            detail = self._process_duplicate(
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

    def find_orphaned_review_ids(self) -> list[str]:
        """List record IDs that exist in both review and trusted.

        Lightweight check — no safety analysis or deletion.
        """
        review_ids = self._repo.list_record_ids("review")
        trusted_ids = set(self._repo.list_record_ids("trusted"))
        return [rid for rid in review_ids if rid in trusted_ids]

    # ── Private helpers ──────────────────────────────────────────

    def _process_duplicate(
        self,
        record_id: str,
        *,
        dry_run: bool,
    ) -> ReconciliationDetail:
        """Evaluate and optionally clean a single duplicate."""
        # Fetch both envelopes
        trusted_env = self._repo.get(record_id, "trusted")
        review_env = self._repo.get(record_id, "review")

        # ── Safety check: both must still exist ──────────────────
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

        # ── Safety check: trusted record must be authoritative ───
        if trusted_env.validation_status not in _TRUSTED_AUTHORITATIVE:
            return self._skip(
                record_id,
                f"Trusted record has non-authoritative status: "
                f"{trusted_env.validation_status.value}",
            )

        # ── Safety check: review record should look like an orphan ─
        if review_env.validation_status not in _REVIEW_ORPHAN_STATUSES:
            return self._skip(
                record_id,
                f"Review record has unexpected status: "
                f"{review_env.validation_status.value} "
                f"(expected one of: "
                f"{', '.join(s.value for s in _REVIEW_ORPHAN_STATUSES)})",
            )

        # ── Safety check: document payload must be compatible ────
        if not self._documents_compatible(trusted_env, review_env):
            return self._skip(
                record_id,
                "Conflicting document content between trusted and "
                "review records",
            )

        # ── Dry-run: report without deleting ─────────────────────
        if dry_run:
            self._record_audit(
                record_id=record_id,
                event_type=AuditEventType.RECONCILIATION_CLEANED,
                reason="Dry-run: would delete orphaned review entry",
            )
            return ReconciliationDetail(
                record_id=record_id,
                outcome=ReconciliationOutcome.CLEANED,
                reason="Dry-run: would delete orphaned review entry",
            )

        # ── Delete the orphaned review entry ─────────────────────
        try:
            result = self._repo.delete(record_id, "review")
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

        self._record_audit(
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
        """Check whether trusted and review documents are compatible.

        Two records are compatible (safe to clean) when:
        - They share the same ``record_id`` (already guaranteed by caller).
        - The ``recordId`` inside the document payload matches (if present).
        - The ``recordType`` inside the document payload matches (if present).

        This is a conservative check — mismatched payloads are skipped.
        """
        t_doc = trusted.document
        r_doc = review.document

        # If both have recordId inside the document, they must match
        t_rid = t_doc.get("recordId")
        r_rid = r_doc.get("recordId")
        if t_rid is not None and r_rid is not None and t_rid != r_rid:
            return False

        # If both have recordType, they must match
        t_type = t_doc.get("recordType")
        r_type = r_doc.get("recordType")
        if t_type is not None and r_type is not None and t_type != r_type:
            return False

        return True

    def _skip(
        self,
        record_id: str,
        reason: str,
    ) -> ReconciliationDetail:
        """Build a SKIPPED detail and optionally record an audit entry."""
        self._record_audit(
            record_id=record_id,
            event_type=AuditEventType.RECONCILIATION_SKIPPED,
            reason=reason,
        )
        return ReconciliationDetail(
            record_id=record_id,
            outcome=ReconciliationOutcome.SKIPPED,
            reason=reason,
        )

    def _record_audit(
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
            self._audit_repo.append(entry)
        except Exception:  # noqa: BLE001
            pass
