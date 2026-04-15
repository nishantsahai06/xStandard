"""Batch processing service — orchestrates multiple document inputs sequentially.

Wraps the existing single-item ``FaultMappingUseCase.execute()`` and
``FaultModulePersistenceService.persist()`` in a loop with per-item
error isolation.

Design
──────
• **Orchestration only** — no mapping/validation/persistence logic
  is duplicated.  Each item flows through the same pipeline as a
  single-item ``POST /process`` call.
• **Partial success** — one item failing does not prevent the rest
  of the batch from being processed.
• **Structured results** — returns ``BatchReport`` with per-item
  ``BatchItemResult`` entries and aggregate counters.
• Depends on the existing ``FaultMappingUseCase`` (sync) and
  ``FaultModulePersistenceService`` (sync).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fault_mapper.domain.models import DocumentPipelineOutput
from fault_mapper.domain.value_objects import BatchItemResult, BatchReport

if TYPE_CHECKING:
    from fault_mapper.application.fault_mapping_use_case import (
        FaultMappingUseCase,
    )
    from fault_mapper.application.fault_module_persistence_service import (
        FaultModulePersistenceService,
    )


class FaultBatchProcessingService:
    """Sync batch processor — runs items sequentially.

    Parameters
    ----------
    use_case : FaultMappingUseCase
        The single-item mapping pipeline.
    persistence : FaultModulePersistenceService
        The single-item persistence service.
    """

    def __init__(
        self,
        use_case: FaultMappingUseCase,
        persistence: FaultModulePersistenceService,
    ) -> None:
        self._use_case = use_case
        self._persistence = persistence

    def process_batch(
        self,
        items: list[DocumentPipelineOutput],
    ) -> BatchReport:
        """Process a list of documents through the full pipeline.

        Each item is independently mapped → validated → persisted.
        Failures are isolated — remaining items continue.

        Parameters
        ----------
        items : list[DocumentPipelineOutput]
            Already-normalised document inputs.

        Returns
        -------
        BatchReport
            Aggregate report with per-item results.
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
                if item_result.collection == "trusted":
                    persisted_trusted += 1
                elif item_result.collection == "review":
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
                validation_status=module.validation_status.value,
                review_status=module.review_status.value,
                mode=module.mode.value if module.mode else None,
                mapping_version=module.mapping_version,
                error=f"Persistence failed: {exc}",
            )

        return BatchItemResult(
            source_id=source_id,
            success=result.success,
            record_id=module.record_id,
            validation_status=module.validation_status.value,
            review_status=module.review_status.value,
            collection=result.collection or None,
            persisted=result.success,
            error=result.error,
            mode=module.mode.value if module.mode else None,
            mapping_version=module.mapping_version,
        )
