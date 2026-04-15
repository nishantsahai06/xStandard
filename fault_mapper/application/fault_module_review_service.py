"""Review workflow service — promotes or rejects review-queue modules.

Sits in the application layer alongside the persistence service.
Handles the review → trusted promotion flow and the rejection flow.

Promotion (approve)
───────────────────
1. Fetch the envelope from the ``"review"`` collection.
2. Rebuild a new envelope targeting the ``"trusted"`` collection
   with ``validation_status=APPROVED`` and ``review_status=APPROVED``.
3. Save the new envelope to the trusted collection.
4. Delete the original from the review collection.
5. Optionally invoke the ``TrustedModuleHandoffPort`` hook.
6. Optionally record an audit entry (best-effort).

Rejection
─────────
1. Fetch the envelope from the ``"review"`` collection.
2. Rebuild with ``validation_status=REJECTED`` and
   ``review_status=REJECTED``.
3. Save in-place in the review collection (audit trail preserved).
4. Record an audit entry capturing the rejection reason.

Audit logging
─────────────
• An optional ``AuditRepositoryPort`` captures structured events
  on both approve and reject.
• Audit writes are best-effort: if the audit repository fails,
  the primary operation (status update / promotion) still succeeds
  and the error is noted but not propagated.
• No audit entry is created when the review item is missing
  (no orphan audit records).

Design
──────
• Depends only on ``FaultModuleRepositoryPort`` (domain port).
• Optional ``TrustedModuleHandoffPort`` for downstream hooks.
• Optional ``AuditRepositoryPort`` for audit logging.
• Produces ``PersistenceResult`` value objects for every operation.
• Never touches the domain model directly — works exclusively with
  persisted ``PersistenceEnvelope`` instances.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fault_mapper.domain.enums import (
    AuditEventType,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.ports import FaultModuleRepositoryPort
from fault_mapper.domain.value_objects import (
    AuditEntry,
    PersistenceEnvelope,
    PersistenceResult,
)

if TYPE_CHECKING:
    from fault_mapper.domain.ports import (
        AuditRepositoryPort,
        TrustedModuleHandoffPort,
    )


class FaultModuleReviewService:
    """Application service that manages the review → trusted workflow.

    Parameters
    ----------
    repository : FaultModuleRepositoryPort
        The same repository used by the persistence service.
    handoff : TrustedModuleHandoffPort | None
        Optional downstream hook invoked after promotion.
    audit_repo : AuditRepositoryPort | None
        Optional audit repository for recording review events.
    """

    def __init__(
        self,
        repository: FaultModuleRepositoryPort,
        handoff: TrustedModuleHandoffPort | None = None,
        audit_repo: AuditRepositoryPort | None = None,
    ) -> None:
        self._repo = repository
        self._handoff = handoff
        self._audit_repo = audit_repo

    # ── Public API ───────────────────────────────────────────────

    def approve(
        self,
        record_id: str,
        *,
        reason: str = "",
        performed_by: str | None = None,
    ) -> PersistenceResult:
        """Promote a review-queue module to the trusted collection.

        Steps
        -----
        1. Fetch from ``"review"``.
        2. Build a trusted envelope (APPROVED / APPROVED).
        3. Save to ``"trusted"``.
        4. Delete from ``"review"``.
        5. Fire handoff hook (best-effort).
        6. Record audit entry (best-effort).

        Returns
        -------
        PersistenceResult
            Result of the trusted-collection write.
        """
        # ── Fetch from review ────────────────────────────────────
        review_env = self._repo.get(record_id, "review")
        if review_env is None:
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="review",
                error=(
                    f"Module {record_id!r} not found in review collection."
                ),
            )

        # ── Build trusted envelope ───────────────────────────────
        now = datetime.now(timezone.utc).isoformat()
        trusted_env = replace(
            review_env,
            collection="trusted",
            validation_status=ValidationStatus.APPROVED,
            review_status=ReviewStatus.APPROVED,
            stored_at=now,
        )

        # ── Save to trusted ──────────────────────────────────────
        try:
            result = self._repo.save(trusted_env)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="trusted",
                error=f"Trusted write failed: {exc}",
            )

        if not result.success:
            return result

        # ── Remove from review ───────────────────────────────────
        try:
            self._repo.delete(record_id, "review")
        except Exception:  # noqa: BLE001
            # Promotion succeeded — review cleanup is best-effort.
            pass

        # ── Downstream handoff (best-effort) ─────────────────────
        if self._handoff is not None:
            try:
                self._handoff.on_module_stored(trusted_env)
            except Exception:  # noqa: BLE001
                # Handoff failures do not roll back the promotion.
                pass

        # ── Audit entry (best-effort) ────────────────────────────
        self._record_audit(
            record_id=record_id,
            event_type=AuditEventType.REVIEW_APPROVED,
            reason=reason,
            performed_by=performed_by,
            timestamp=now,
            validation_status=ValidationStatus.APPROVED,
            review_status=ReviewStatus.APPROVED,
            collection="trusted",
        )

        return result

    def reject(
        self,
        record_id: str,
        reason: str = "",
        *,
        performed_by: str | None = None,
    ) -> PersistenceResult:
        """Reject a review-queue module.

        The module stays in the review collection with updated
        statuses for audit trail purposes.  An audit entry is
        recorded with the rejection reason.

        Parameters
        ----------
        record_id : str
            The module to reject.
        reason : str
            Rejection reason (captured in the audit entry).
        performed_by : str | None
            Identity of the reviewer performing the rejection.

        Returns
        -------
        PersistenceResult
            Result of the in-place status update.
        """
        review_env = self._repo.get(record_id, "review")
        if review_env is None:
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="review",
                error=(
                    f"Module {record_id!r} not found in review collection."
                ),
            )

        now = datetime.now(timezone.utc).isoformat()
        rejected_env = replace(
            review_env,
            validation_status=ValidationStatus.REJECTED,
            review_status=ReviewStatus.REJECTED,
            stored_at=now,
        )

        try:
            result = self._repo.save(rejected_env)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="review",
                error=f"Review update failed: {exc}",
            )

        if not result.success:
            return result

        # ── Audit entry (best-effort) ────────────────────────────
        self._record_audit(
            record_id=record_id,
            event_type=AuditEventType.REVIEW_REJECTED,
            reason=reason,
            performed_by=performed_by,
            timestamp=now,
            validation_status=ValidationStatus.REJECTED,
            review_status=ReviewStatus.REJECTED,
            collection="review",
        )

        return result

    def get_review_item(
        self,
        record_id: str,
    ) -> PersistenceEnvelope | None:
        """Fetch a single item from the review queue.

        Returns
        -------
        PersistenceEnvelope | None
            The envelope if found, else None.
        """
        return self._repo.get(record_id, "review")

    def list_review_items(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        """List items in the review queue with pagination."""
        return self._repo.list_by_collection(
            "review", limit=limit, offset=offset,
        )

    def count_review_items(self) -> int:
        """Count items currently in the review queue."""
        return self._repo.count("review")

    # ── Private helpers ──────────────────────────────────────────

    def _record_audit(
        self,
        *,
        record_id: str,
        event_type: AuditEventType,
        reason: str,
        performed_by: str | None,
        timestamp: str,
        validation_status: ValidationStatus,
        review_status: ReviewStatus,
        collection: str,
    ) -> None:
        """Write an audit entry (best-effort — swallows exceptions)."""
        if self._audit_repo is None:
            return
        try:
            entry = AuditEntry(
                record_id=record_id,
                event_type=event_type,
                reason=reason,
                timestamp=timestamp,
                performed_by=performed_by,
                validation_status=validation_status,
                review_status=review_status,
                collection=collection,
            )
            self._audit_repo.append(entry)
        except Exception:  # noqa: BLE001
            # Audit failure must not block the primary operation.
            pass
