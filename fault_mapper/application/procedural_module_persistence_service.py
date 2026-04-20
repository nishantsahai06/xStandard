"""Procedural module persistence service — routes validated modules to storage.

Concrete configuration of :class:`ModulePersistenceService` for
procedural data modules.  Collection names are prefixed with
``procedural_`` to keep procedural data segregated from fault data in
the same repository backend.

Differences from the fault configuration:
  * Routing driver — ``ReviewStatus`` on ``module.review_status``.
  * Collection map — APPROVED → ``procedural_trusted``,
    NOT_REVIEWED → ``procedural_review``.
  * Envelope ``validation_status`` is synthesised from review status.
  * No post-persist lifecycle transition.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fault_mapper.application._module_persistence_base import (
    ModulePersistenceService,
    PersistencePolicy,
)
from fault_mapper.domain.enums import ReviewStatus, ValidationStatus
from fault_mapper.domain.ports import FaultModuleRepositoryPort
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


def _build_procedural_envelope(
    module: S1000DProceduralDataModule,
    status: ReviewStatus,
    collection: str,
    document: dict,
    stored_at: str,
) -> PersistenceEnvelope:
    synthesised_validation = (
        ValidationStatus.APPROVED
        if status is ReviewStatus.APPROVED
        else ValidationStatus.REVIEW_REQUIRED
    )
    return PersistenceEnvelope(
        record_id=module.record_id,
        collection=collection,
        document=document,
        validation_status=synthesised_validation,
        review_status=status,
        mapping_version=module.mapping_version,
        stored_at=stored_at,
    )


def _procedural_post_persist(
    module: S1000DProceduralDataModule,
    status: ReviewStatus,
    result: PersistenceResult,
) -> None:
    """No post-persist lifecycle transition for procedural modules."""
    return None


class ProceduralModulePersistenceService(
    ModulePersistenceService[S1000DProceduralDataModule, ReviewStatus],
):
    """Application service that persists validated procedural data modules.

    Parameters
    ----------
    repository : FaultModuleRepositoryPort
        The storage backend (MongoDB, in-memory, …).  Shared with fault
        persistence — collections are namespace-separated by prefix.
    serializer : Callable[[S1000DProceduralDataModule], dict[str, Any]], optional
        Function that converts a procedural domain module to a JSON dict.
        Default: ``serialize_procedural_module`` from the serialiser adapter.
    """

    def __init__(
        self,
        repository: FaultModuleRepositoryPort,
        serializer: "Callable[[S1000DProceduralDataModule], dict[str, Any]] | None" = None,
    ) -> None:
        if serializer is None:
            from fault_mapper.adapters.secondary.procedural_module_serializer import (
                serialize_procedural_module,
            )
            serializer = serialize_procedural_module

        policy: PersistencePolicy[
            S1000DProceduralDataModule, ReviewStatus,
        ] = PersistencePolicy(
            get_status=lambda m: m.review_status,
            persistable_statuses=_PERSISTABLE_STATUSES,
            collection_map=_COLLECTION_MAP,
            serializer=serializer,
            build_envelope=_build_procedural_envelope,
            post_persist=_procedural_post_persist,
            status_field_label="review_status",
            eligible_status_names=("APPROVED", "NOT_REVIEWED"),
            default_collection="procedural_trusted",
        )
        super().__init__(repository, policy)
