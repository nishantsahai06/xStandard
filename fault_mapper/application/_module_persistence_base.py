"""Generic module persistence service + policy strategy.

Both the fault and procedural pipelines route validated modules to a
MongoDB repository based on a per-module status field.  The orchestration
is identical:

  1. Read the driving status off the module.
  2. Guard — reject modules whose status is not persistable.
  3. Serialise the module to a JSON dict.
  4. Build a :class:`PersistenceEnvelope`.
  5. Delegate to the repository port.
  6. Apply a post-persist lifecycle transition (fault only).

What differs between pipelines is captured in :class:`PersistencePolicy`:
  * which field drives routing (``validation_status`` vs ``review_status``);
  * the status enum (:class:`ValidationStatus` vs :class:`ReviewStatus`);
  * the ``status → collection`` map;
  * the serializer;
  * how to construct the envelope's ``validation_status``/``review_status`` pair;
  * whether to mutate the module after a successful write.

The concrete services (:class:`FaultModulePersistenceService` and
:class:`ProceduralModulePersistenceService`) are thin subclasses that
construct the right policy and forward all methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Mapping,
    TypeVar,
)

from fault_mapper.domain.ports import FaultModuleRepositoryPort
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)

if TYPE_CHECKING:
    pass


TModule = TypeVar("TModule")
TStatus = TypeVar("TStatus")


@dataclass(frozen=True)
class PersistencePolicy(Generic[TModule, TStatus]):
    """Strategy object describing how one module type gets persisted.

    Every field is a pure callable or a value — no I/O, no hidden state.
    """

    #: How to read the driving status value off the module.
    get_status: Callable[[TModule], TStatus]

    #: Status values for which the module may be persisted.
    persistable_statuses: frozenset[TStatus]

    #: Status → target collection name.
    collection_map: Mapping[TStatus, str]

    #: Convert a module into a JSON-serialisable dict.
    serializer: Callable[[TModule], dict[str, Any]]

    #: Build a :class:`PersistenceEnvelope` from module + metadata.
    build_envelope: Callable[
        [TModule, TStatus, str, dict[str, Any], str],
        PersistenceEnvelope,
    ]

    #: Apply a post-persist side-effect on success (e.g. status→STORED).
    post_persist: Callable[[TModule, TStatus, PersistenceResult], None]

    #: Human-readable label used in guard error messages.
    status_field_label: str

    #: Eligible status names used to render guard error messages.
    eligible_status_names: tuple[str, ...]

    #: Default collection for retrieve / list / count convenience methods.
    default_collection: str


class ModulePersistenceService(Generic[TModule, TStatus]):
    """Generic application service that persists validated modules.

    Constructed with a :class:`PersistencePolicy` that captures all
    pipeline-specific behaviour.  This class contains the workflow
    that is identical for every pipeline and nothing else.
    """

    def __init__(
        self,
        repository: FaultModuleRepositoryPort,
        policy: PersistencePolicy[TModule, TStatus],
    ) -> None:
        self._repo = repository
        self._policy = policy

    # ── Public API ───────────────────────────────────────────────

    def persist(self, module: TModule) -> PersistenceResult:
        """Route *module* to the collection dictated by its status.

        On ineligible status returns a failure result with an empty
        ``collection``.  On success applies any pipeline-specific
        post-persist lifecycle transition and returns the repository's
        result unchanged.
        """
        policy = self._policy
        status = policy.get_status(module)
        record_id = module.record_id  # type: ignore[attr-defined]

        # Guard — not eligible for persistence
        if status not in policy.persistable_statuses:
            eligible = " and ".join(policy.eligible_status_names)
            status_value = getattr(status, "value", status)
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection="",
                error=(
                    f"Module {record_id!r} has "
                    f"{policy.status_field_label} {status_value!r} — "
                    f"only {eligible} modules are persisted."
                ),
            )

        collection = policy.collection_map[status]

        # Serialise
        try:
            document = policy.serializer(module)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection=collection,
                error=f"Serialisation failed: {exc}",
            )

        # Build envelope
        now = datetime.now(timezone.utc).isoformat()
        envelope = policy.build_envelope(
            module, status, collection, document, now,
        )

        # Delegate to repository
        try:
            result = self._repo.save(envelope)
        except Exception as exc:  # noqa: BLE001
            return PersistenceResult(
                success=False,
                record_id=record_id,
                collection=collection,
                error=f"Repository write failed: {exc}",
            )

        # Post-persist lifecycle transition (e.g. APPROVED → STORED)
        policy.post_persist(module, status, result)
        return result

    def retrieve(
        self,
        record_id: str,
        collection: str | None = None,
    ) -> PersistenceEnvelope | None:
        """Retrieve a stored module envelope by record ID."""
        target = collection or self._policy.default_collection
        return self._repo.get(record_id, target)

    def list_modules(
        self,
        collection: str | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        """List stored envelopes with pagination."""
        target = collection or self._policy.default_collection
        return self._repo.list_by_collection(
            target, limit=limit, offset=offset,
        )

    def count_modules(self, collection: str | None = None) -> int:
        """Count stored modules in a collection."""
        target = collection or self._policy.default_collection
        return self._repo.count(target)
