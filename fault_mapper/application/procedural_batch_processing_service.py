"""Sync batch processing service for procedural modules.

Mirrors ``FaultBatchProcessingService`` structurally.  Wraps the
``ProceduralMappingUseCase.execute()`` and
``ProceduralModulePersistenceService.persist()`` in a loop with
per-item error isolation.

Key differences from fault batch:
• Routes on ``review_status`` (not ``validation_status``).
• Collection names: ``procedural_trusted`` / ``procedural_review``.
• No ``mode`` field — uses ``module_type`` mapped to the ``mode``
  slot in ``BatchItemResult`` for consistency.
• No ``validation_status`` on the procedural model — left as None.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fault_mapper.domain.models import DocumentPipelineOutput
from fault_mapper.domain.value_objects import BatchItemResult, BatchReport

if TYPE_CHECKING:
    from fault_mapper.application.procedural_mapping_use_case import (
        ProceduralMappingUseCase,
    )
    from fault_mapper.application.procedural_module_persistence_service import (
        ProceduralModulePersistenceService,
    )


class ProceduralBatchProcessingService:
    """Sync batch processor for procedural modules.

    Parameters
    ----------
    use_case : ProceduralMappingUseCase
        The single-item procedural mapping pipeline.
    persistence : ProceduralModulePersistenceService
        The single-item procedural persistence service.
    """

    def __init__(
        self,
        use_case: ProceduralMappingUseCase,
        persistence: ProceduralModulePersistenceService,
    ) -> None:
        self._use_case = use_case
        self._persistence = persistence

    def process_batch(
        self,
        items: list[DocumentPipelineOutput],
    ) -> BatchReport:
        """Process a list of documents through the procedural pipeline.

        Each item is independently mapped → validated → persisted.
        Failures are isolated — remaining items continue.
        """
        t0 = time.monotonic()
        results: list[BatchItemResult] = []
        succeeded = 0
        failed = 0
        persisted_trusted = 0
        persisted_review = 0
        not_persisted = 0

        for source in items:
            item_result = self._process_one(source)
            results.append(item_result)

            if item_result.success:
                succeeded += 1
                if item_result.collection == "procedural_trusted":
                    persisted_trusted += 1
                elif item_result.collection == "procedural_review":
                    persisted_review += 1
                else:
                    not_persisted += 1
            else:
                failed += 1
                if not item_result.persisted:
                    not_persisted += 1

        elapsed_ms = (time.monotonic() - t0) * 1000

        return BatchReport(
            total=len(items),
            succeeded=succeeded,
            failed=failed,
            persisted_trusted=persisted_trusted,
            persisted_review=persisted_review,
            not_persisted=not_persisted,
            elapsed_ms=elapsed_ms,
            items=results,
        )

    def _process_one(
        self,
        source: DocumentPipelineOutput,
    ) -> BatchItemResult:
        """Process a single item with full error isolation."""
        source_id = source.id

        # ── Map + validate ───────────────────────────────────────
        try:
            module = self._use_case.execute(source)
        except Exception as exc:  # noqa: BLE001
            return BatchItemResult(
                source_id=source_id,
                success=False,
                error=f"Mapping failed: {exc}",
            )

        # ── Persist ──────────────────────────────────────────────
        try:
            result = self._persistence.persist(module)
        except Exception as exc:  # noqa: BLE001
            return BatchItemResult(
                source_id=source_id,
                success=False,
                record_id=module.record_id,
                review_status=module.review_status.value,
                mode=module.module_type.value,
                mapping_version=module.mapping_version,
                error=f"Persistence failed: {exc}",
            )

        return BatchItemResult(
            source_id=source_id,
            success=result.success,
            record_id=module.record_id,
            review_status=module.review_status.value,
            collection=result.collection or None,
            persisted=result.success,
            error=result.error,
            mode=module.module_type.value,
            mapping_version=module.mapping_version,
        )
