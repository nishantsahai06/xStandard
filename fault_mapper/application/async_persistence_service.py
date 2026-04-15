"""Async persistence service — async counterpart of ``FaultModulePersistenceService``.

Same business logic, but delegates to ``AsyncFaultModuleRepositoryPort``
via ``await``.  The domain model and value objects are unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fault_mapper.domain.enums import ValidationStatus
from fault_mapper.domain.models import S1000DFaultDataModule
from fault_mapper.domain.ports import AsyncFaultModuleRepositoryPort
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


_PERSISTABLE_STATUSES: frozenset[ValidationStatus] = frozenset(
    {ValidationStatus.APPROVED, ValidationStatus.REVIEW_REQUIRED},
)

_COLLECTION_MAP: dict[ValidationStatus, str] = {
    ValidationStatus.APPROVED: "trusted",
    ValidationStatus.REVIEW_REQUIRED: "review",
}


class AsyncFaultModulePersistenceService:
    """Async application service that persists validated fault modules."""

    def __init__(
        self,
        repository: AsyncFaultModuleRepositoryPort,
        serializer: Callable[[S1000DFaultDataModule], dict[str, Any]] | None = None,
    ) -> None:
        self._repo = repository
        if serializer is None:
            from fault_mapper.adapters.secondary.module_serializer import (
                serialize_module,
            )
            self._serializer = serialize_module
        else:
            self._serializer = serializer

    async def persist(self, module: S1000DFaultDataModule) -> PersistenceResult:
        status = module.validation_status

        if status not in _PERSISTABLE_STATUSES:
            return PersistenceResult(
                success=False,
                record_id=module.record_id,
                collection="",
                error=(
                    f"Module {module.record_id!r} has validation_status "
                    f"{status.value!r} — only APPROVED and REVIEW_REQUIRED "
                    f"modules are persisted."
                ),
            )

        collection = _COLLECTION_MAP[status]

        try:
            document = self._serializer(module)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=module.record_id,
                collection=collection,
                error=f"Serialisation failed: {exc}",
            )

        now = datetime.now(timezone.utc).isoformat()
        envelope = PersistenceEnvelope(
            record_id=module.record_id,
            collection=collection,
            document=document,
            validation_status=status,
            review_status=module.review_status,
            mapping_version=module.mapping_version,
            stored_at=now,
        )

        try:
            result = await self._repo.save(envelope)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=module.record_id,
                collection=collection,
                error=f"Repository write failed: {exc}",
            )

        if result.success and status is ValidationStatus.APPROVED:
            module.validation_status = ValidationStatus.STORED

        return result

    async def retrieve(
        self, record_id: str, collection: str = "trusted",
    ) -> PersistenceEnvelope | None:
        return await self._repo.get(record_id, collection)

    async def list_modules(
        self, collection: str = "trusted", *, limit: int = 100, offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return await self._repo.list_by_collection(
            collection, limit=limit, offset=offset,
        )

    async def count_modules(self, collection: str = "trusted") -> int:
        return await self._repo.count(collection)
