"""Async persistence service for procedural modules.

Async counterpart of ``ProceduralModulePersistenceService``.  Same
business logic, but delegates to ``AsyncFaultModuleRepositoryPort``
via ``await``.

Routing rules
─────────────
  APPROVED         → ``"procedural_trusted"``  collection
  NOT_REVIEWED     → ``"procedural_review"``   collection
  REJECTED         → NOT persisted
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.ports import AsyncFaultModuleRepositoryPort
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


_PERSISTABLE_STATUSES: frozenset[ReviewStatus] = frozenset(
    {
        ReviewStatus.APPROVED,
        ReviewStatus.NOT_REVIEWED,
    },
)

_COLLECTION_MAP: dict[ReviewStatus, str] = {
    ReviewStatus.APPROVED: "procedural_trusted",
    ReviewStatus.NOT_REVIEWED: "procedural_review",
}


class AsyncProceduralModulePersistenceService:
    """Async application service that persists validated procedural modules.

    Parameters
    ----------
    repository : AsyncFaultModuleRepositoryPort
        The async storage backend.
    serializer : Callable | None
        Converts a procedural module to a JSON dict.
    """

    def __init__(
        self,
        repository: AsyncFaultModuleRepositoryPort,
        serializer: Callable[[S1000DProceduralDataModule], dict[str, Any]] | None = None,
    ) -> None:
        self._repo = repository
        if serializer is None:
            from fault_mapper.adapters.secondary.procedural_module_serializer import (
                serialize_procedural_module,
            )
            self._serializer = serialize_procedural_module
        else:
            self._serializer = serializer

    async def persist(
        self, module: S1000DProceduralDataModule,
    ) -> PersistenceResult:
        """Persist a validated procedural module to the appropriate collection."""
        status = module.review_status

        if status not in _PERSISTABLE_STATUSES:
            return PersistenceResult(
                success=False,
                record_id=module.record_id,
                collection="",
                error=(
                    f"Module {module.record_id!r} has review_status "
                    f"{status.value!r} — only APPROVED and NOT_REVIEWED "
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
            validation_status=(
                ValidationStatus.APPROVED
                if status is ReviewStatus.APPROVED
                else ValidationStatus.REVIEW_REQUIRED
            ),
            review_status=status,
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

        return result

    async def retrieve(
        self, record_id: str, collection: str = "procedural_trusted",
    ) -> PersistenceEnvelope | None:
        return await self._repo.get(record_id, collection)

    async def list_modules(
        self,
        collection: str = "procedural_trusted",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return await self._repo.list_by_collection(
            collection, limit=limit, offset=offset,
        )

    async def count_modules(
        self, collection: str = "procedural_trusted",
    ) -> int:
        return await self._repo.count(collection)
