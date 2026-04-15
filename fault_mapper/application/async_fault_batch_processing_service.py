"""Async batch processing service — orchestrates multiple document inputs
with optional bounded concurrency.

Async counterpart of ``FaultBatchProcessingService``.  The mapping use
case is always sync (CPU-bound) so it runs via ``asyncio.to_thread``.
Persistence uses the async persistence service directly.

Concurrency
───────────
An ``asyncio.Semaphore`` caps the number of items processed in
parallel.  Default ``max_concurrency=5`` provides useful throughput
for I/O-bound persistence without overwhelming the backend.  Set to
``1`` for strictly sequential processing.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from fault_mapper.domain.models import DocumentPipelineOutput
from fault_mapper.domain.value_objects import BatchItemResult, BatchReport

if TYPE_CHECKING:
    from fault_mapper.application.fault_mapping_use_case import (
        FaultMappingUseCase,
    )


class AsyncFaultBatchProcessingService:
    """Async batch processor with bounded concurrency.

    Parameters
    ----------
    use_case : FaultMappingUseCase
        The single-item mapping pipeline (sync — called via to_thread).
    persistence : object
        An async persistence service with an ``async persist(module)``
        method (``AsyncFaultModulePersistenceService`` or its
        instrumented wrapper).
    max_concurrency : int
        Maximum number of items processed in parallel.  Defaults to 5.
    """

    def __init__(
        self,
        use_case: FaultMappingUseCase,
        persistence: object,
        max_concurrency: int = 5,
    ) -> None:
        self._use_case = use_case
        self._persistence = persistence
        self._max_concurrency = max(1, max_concurrency)

    async def process_batch(
        self,
        items: list[DocumentPipelineOutput],
    ) -> BatchReport:
        """Process a list of documents through the full pipeline.

        Items are processed concurrently up to ``max_concurrency``.
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
        sem = asyncio.Semaphore(self._max_concurrency)

        async def _bounded(source: DocumentPipelineOutput) -> BatchItemResult:
            async with sem:
                return await self._process_one(source)

        results = await asyncio.gather(
            *(_bounded(src) for src in items),
        )

        succeeded = 0
        failed = 0
        persisted_trusted = 0
        persisted_review = 0
        not_persisted = 0

        for r in results:
            if r.success:
                succeeded += 1
                if r.collection == "trusted":
                    persisted_trusted += 1
                elif r.collection == "review":
                    persisted_review += 1
                else:
                    not_persisted += 1
            else:
                failed += 1
                if not r.persisted:
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
            items=list(results),
        )

    async def _process_one(
        self,
        source: DocumentPipelineOutput,
    ) -> BatchItemResult:
        """Process a single item with full error isolation."""
        source_id = source.id

        # ── Map + validate (sync use case via to_thread) ─────────
        try:
            module = await asyncio.to_thread(
                self._use_case.execute, source,
            )
        except Exception as exc:  # noqa: BLE001
            return BatchItemResult(
                source_id=source_id,
                success=False,
                error=f"Mapping failed: {exc}",
            )

        # ── Persist (async) ──────────────────────────────────────
        try:
            result = await self._persistence.persist(module)  # type: ignore[union-attr]
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
