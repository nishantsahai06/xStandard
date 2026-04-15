"""Persistence service — routes validated modules to durable storage.

Sits in the application layer between the use case / validator and
the repository port.  Decides which collection receives the module
based on its ``validation_status`` after validation completes.

Routing rules
─────────────
  APPROVED         → ``"trusted"``  collection, status → STORED
  REVIEW_REQUIRED  → ``"review"``   collection, status unchanged
  *_FAILED / REJECTED → NOT persisted (returned as failure result)

Design
──────
• Depends only on ``FaultModuleRepositoryPort`` (domain port).
• Uses ``serialize_module()`` from the serialiser adapter to convert
  the domain model to a JSON-serialisable dict.
• Produces ``PersistenceResult`` value objects — never mutates the
  module except to set ``validation_status = STORED`` on success.
• This is a standalone service, NOT bolted onto the use case.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fault_mapper.domain.enums import ValidationStatus
from fault_mapper.domain.models import S1000DFaultDataModule
from fault_mapper.domain.ports import FaultModuleRepositoryPort
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


# Validation statuses that are eligible for persistence
_PERSISTABLE_STATUSES: frozenset[ValidationStatus] = frozenset(
    {
        ValidationStatus.APPROVED,
        ValidationStatus.REVIEW_REQUIRED,
    },
)

# Status → target collection mapping
_COLLECTION_MAP: dict[ValidationStatus, str] = {
    ValidationStatus.APPROVED: "trusted",
    ValidationStatus.REVIEW_REQUIRED: "review",
}


class FaultModulePersistenceService:
    """Application service that persists validated fault data modules.

    Parameters
    ----------
    repository : FaultModuleRepositoryPort
        The storage backend (MongoDB, in-memory, …).
    serializer : Callable[[S1000DFaultDataModule], dict[str, Any]]
        Function that converts a domain module to a JSON dict.
        Default: ``serialize_module`` from the module-serialiser adapter.
    """

    def __init__(
        self,
        repository: FaultModuleRepositoryPort,
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

    # ── Public API ───────────────────────────────────────────────

    def persist(self, module: S1000DFaultDataModule) -> PersistenceResult:
        """Persist a validated module to the appropriate collection.

        1. Check eligibility (status must be APPROVED or REVIEW_REQUIRED).
        2. Serialise module to JSON dict.
        3. Build ``PersistenceEnvelope`` with metadata.
        4. Delegate to the repository port.
        5. On success for APPROVED modules, set status → STORED.

        Parameters
        ----------
        module : S1000DFaultDataModule
            A module that has been through the validation pipeline.

        Returns
        -------
        PersistenceResult
            Success/failure of the persistence operation.
        """
        status = module.validation_status

        # ── Guard: not eligible for persistence ──────────────────
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

        # ── Resolve target collection ────────────────────────────
        collection = _COLLECTION_MAP[status]

        # ── Serialise ────────────────────────────────────────────
        try:
            document = self._serializer(module)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=module.record_id,
                collection=collection,
                error=f"Serialisation failed: {exc}",
            )

        # ── Build envelope ───────────────────────────────────────
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

        # ── Delegate to repository ───────────────────────────────
        try:
            result = self._repo.save(envelope)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=module.record_id,
                collection=collection,
                error=f"Repository write failed: {exc}",
            )

        # ── Post-persist lifecycle transition ────────────────────
        if result.success and status is ValidationStatus.APPROVED:
            module.validation_status = ValidationStatus.STORED

        return result

    def retrieve(
        self,
        record_id: str,
        collection: str = "trusted",
    ) -> PersistenceEnvelope | None:
        """Retrieve a stored module envelope by record ID.

        Parameters
        ----------
        record_id : str
            The module's record_id.
        collection : str
            Target collection (``"trusted"`` or ``"review"``).

        Returns
        -------
        PersistenceEnvelope | None
            The envelope if found, else None.
        """
        return self._repo.get(record_id, collection)

    def list_modules(
        self,
        collection: str = "trusted",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        """List stored module envelopes with pagination."""
        return self._repo.list_by_collection(
            collection, limit=limit, offset=offset,
        )

    def count_modules(self, collection: str = "trusted") -> int:
        """Count stored modules in a collection."""
        return self._repo.count(collection)
