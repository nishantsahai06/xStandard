"""Fault module persistence service — routes validated modules to storage.

Concrete configuration of :class:`ModulePersistenceService` for fault
data modules.  The full workflow lives in the generic base; this
module only declares the fault-specific policy:

  * Routing driver — ``ValidationStatus`` on ``module.validation_status``.
  * Collection map — APPROVED → ``trusted``, REVIEW_REQUIRED → ``review``.
  * Post-persist — APPROVED → STORED on successful write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fault_mapper.application._module_persistence_base import (
    ModulePersistenceService,
    PersistencePolicy,
)
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


_PERSISTABLE_STATUSES: frozenset[ValidationStatus] = frozenset(
    {
        ValidationStatus.APPROVED,
        ValidationStatus.REVIEW_REQUIRED,
    },
)

_COLLECTION_MAP: dict[ValidationStatus, str] = {
    ValidationStatus.APPROVED: "trusted",
    ValidationStatus.REVIEW_REQUIRED: "review",
}


def _build_fault_envelope(
    module: S1000DFaultDataModule,
    status: ValidationStatus,
    collection: str,
    document: dict,
    stored_at: str,
) -> PersistenceEnvelope:
    return PersistenceEnvelope(
        record_id=module.record_id,
        collection=collection,
        document=document,
        validation_status=status,
        review_status=module.review_status,
        mapping_version=module.mapping_version,
        stored_at=stored_at,
    )


def _fault_post_persist(
    module: S1000DFaultDataModule,
    status: ValidationStatus,
    result: PersistenceResult,
) -> None:
    """APPROVED → STORED after a successful write; otherwise no-op."""
    if result.success and status is ValidationStatus.APPROVED:
        module.validation_status = ValidationStatus.STORED


class FaultModulePersistenceService(
    ModulePersistenceService[S1000DFaultDataModule, ValidationStatus],
):
    """Application service that persists validated fault data modules.

    Parameters
    ----------
    repository : FaultModuleRepositoryPort
        The storage backend (MongoDB, in-memory, …).
    serializer : Callable[[S1000DFaultDataModule], dict[str, Any]], optional
        Function that converts a domain module to a JSON dict.
        Default: ``serialize_module`` from the module-serialiser adapter.
    """

    def __init__(
        self,
        repository: FaultModuleRepositoryPort,
        serializer: "Callable[[S1000DFaultDataModule], dict[str, Any]] | None" = None,
    ) -> None:
        if serializer is None:
            from fault_mapper.adapters.secondary.module_serializer import (
                serialize_module,
            )
            serializer = serialize_module

        policy: PersistencePolicy[S1000DFaultDataModule, ValidationStatus] = (
            PersistencePolicy(
                get_status=lambda m: m.validation_status,
                persistable_statuses=_PERSISTABLE_STATUSES,
                collection_map=_COLLECTION_MAP,
                serializer=serializer,
                build_envelope=_build_fault_envelope,
                post_persist=_fault_post_persist,
                status_field_label="validation_status",
                eligible_status_names=("APPROVED", "REVIEW_REQUIRED"),
                default_collection="trusted",
            )
        )
        super().__init__(repository, policy)
