"""Persistence service — routes validated procedural modules to durable storage.

Sits in the application layer between the use case / validator and
the repository port.  Decides which collection receives the module
based on its ``review_status`` after validation completes.

Routing rules
─────────────
  APPROVED         → ``"procedural_trusted"``  collection
  NOT_REVIEWED     → ``"procedural_review"``   collection
  REJECTED         → NOT persisted (returned as failure result)

Design
──────
• Depends only on ``FaultModuleRepositoryPort`` (shared domain port).
• Uses ``serialize_procedural_module()`` from the serialiser adapter
  to convert the domain model to a JSON-serialisable dict.
• Produces ``PersistenceResult`` value objects — never mutates the
  module except to set ``review_status = APPROVED`` on already-approved
  modules after successful trusted persistence.
• This is a standalone service, NOT bolted onto the use case.
• Collection names are prefixed with ``procedural_`` to segregate
  procedural data from fault data in the same repository backend.

Mirrors ``FaultModulePersistenceService`` structurally.  The key
difference is routing on ``review_status`` (ReviewStatus enum) rather
than ``validation_status`` (ValidationStatus enum), because the
procedural model does not carry a ``validation_status`` field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.domain.ports import FaultModuleRepositoryPort
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


# Review statuses that are eligible for persistence
_PERSISTABLE_STATUSES: frozenset[ReviewStatus] = frozenset(
    {
        ReviewStatus.APPROVED,
        ReviewStatus.NOT_REVIEWED,
    },
)

# ReviewStatus → target collection mapping
_COLLECTION_MAP: dict[ReviewStatus, str] = {
    ReviewStatus.APPROVED: "procedural_trusted",
    ReviewStatus.NOT_REVIEWED: "procedural_review",
}


class ProceduralModulePersistenceService:
    """Application service that persists validated procedural data modules.

    Parameters
    ----------
    repository : FaultModuleRepositoryPort
        The storage backend (MongoDB, in-memory, …).
        Shared with fault persistence — collections are namespace-separated.
    serializer : Callable[[S1000DProceduralDataModule], dict[str, Any]]
        Function that converts a procedural domain module to a JSON dict.
        Default: ``serialize_procedural_module`` from the serialiser adapter.
    """

    def __init__(
        self,
        repository: FaultModuleRepositoryPort,
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

    # ── Public API ───────────────────────────────────────────────

    def persist(self, module: S1000DProceduralDataModule) -> PersistenceResult:
        """Persist a validated procedural module to the appropriate collection.

        1. Check eligibility (review_status must be APPROVED or NOT_REVIEWED).
        2. Serialise module to JSON dict.
        3. Build ``PersistenceEnvelope`` with metadata.
        4. Delegate to the repository port.

        Parameters
        ----------
        module : S1000DProceduralDataModule
            A module that has been through the validation pipeline.

        Returns
        -------
        PersistenceResult
            Success/failure of the persistence operation.
        """
        status = module.review_status

        # ── Guard: not eligible for persistence ──────────────────
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
            validation_status=ValidationStatus.APPROVED if status is ReviewStatus.APPROVED else ValidationStatus.REVIEW_REQUIRED,
            review_status=status,
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

        return result

    def retrieve(
        self,
        record_id: str,
        collection: str = "procedural_trusted",
    ) -> PersistenceEnvelope | None:
        """Retrieve a stored procedural module envelope by record ID.

        Parameters
        ----------
        record_id : str
            The module's record_id.
        collection : str
            Target collection (``"procedural_trusted"`` or ``"procedural_review"``).

        Returns
        -------
        PersistenceEnvelope | None
            The envelope if found, else None.
        """
        return self._repo.get(record_id, collection)

    def list_modules(
        self,
        collection: str = "procedural_trusted",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        """List stored procedural module envelopes with pagination."""
        return self._repo.list_by_collection(
            collection, limit=limit, offset=offset,
        )

    def count_modules(self, collection: str = "procedural_trusted") -> int:
        """Count stored procedural modules in a collection."""
        return self._repo.count(collection)
