"""Async review service — async counterpart of ``FaultModuleReviewService``.

Same business logic (approve, reject, list), but delegates to
``AsyncFaultModuleRepositoryPort`` and optionally
``AsyncAuditRepositoryPort`` via ``await``.
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
from fault_mapper.domain.ports import AsyncFaultModuleRepositoryPort
from fault_mapper.domain.value_objects import (
    AuditEntry,
    PersistenceEnvelope,
    PersistenceResult,
)

if TYPE_CHECKING:
    from fault_mapper.domain.ports import AsyncAuditRepositoryPort


class AsyncFaultModuleReviewService:
    """Async application service for the review → trusted workflow."""

    def __init__(
        self,
        repository: AsyncFaultModuleRepositoryPort,
        audit_repo: AsyncAuditRepositoryPort | None = None,
    ) -> None:
        self._repo = repository
        self._audit_repo = audit_repo

    async def approve(
        self,
        record_id: str,
        *,
        reason: str = "",
        performed_by: str | None = None,
    ) -> PersistenceResult:
        review_env = await self._repo.get(record_id, "review")
        if review_env is None:
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="review",
                error=f"Module {record_id!r} not found in review collection.",
            )

        now = datetime.now(timezone.utc).isoformat()
        trusted_env = replace(
            review_env,
            collection="trusted",
            validation_status=ValidationStatus.APPROVED,
            review_status=ReviewStatus.APPROVED,
            stored_at=now,
        )

        try:
            result = await self._repo.save(trusted_env)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="trusted",
                error=f"Trusted write failed: {exc}",
            )

        if not result.success:
            return result

        try:
            await self._repo.delete(record_id, "review")
        except Exception:  # noqa: BLE001
            pass

        await self._record_audit(
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

    async def reject(
        self,
        record_id: str,
        reason: str = "",
        *,
        performed_by: str | None = None,
    ) -> PersistenceResult:
        review_env = await self._repo.get(record_id, "review")
        if review_env is None:
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="review",
                error=f"Module {record_id!r} not found in review collection.",
            )

        now = datetime.now(timezone.utc).isoformat()
        rejected_env = replace(
            review_env,
            validation_status=ValidationStatus.REJECTED,
            review_status=ReviewStatus.REJECTED,
            stored_at=now,
        )

        try:
            result = await self._repo.save(rejected_env)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="review",
                error=f"Review update failed: {exc}",
            )

        if not result.success:
            return result

        await self._record_audit(
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

    async def get_review_item(
        self, record_id: str,
    ) -> PersistenceEnvelope | None:
        return await self._repo.get(record_id, "review")

    async def list_review_items(
        self, *, limit: int = 100, offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return await self._repo.list_by_collection(
            "review", limit=limit, offset=offset,
        )

    async def count_review_items(self) -> int:
        return await self._repo.count("review")

    async def _record_audit(
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
            await self._audit_repo.append(entry)
        except Exception:  # noqa: BLE001
            pass
