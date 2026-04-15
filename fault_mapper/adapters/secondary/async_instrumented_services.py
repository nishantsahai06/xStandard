"""Async instrumented service wrappers — observability via delegation.

Async counterparts of the sync wrappers in ``instrumented_services.py``.
Each wrapper ``await``s the inner async service and emits metrics
around every public method call.

Wrapper inventory
─────────────────
1. ``AsyncInstrumentedFaultModulePersistenceService``
2. ``AsyncInstrumentedFaultModuleReviewService``
3. ``AsyncInstrumentedFaultModuleReconciliationService``

Note: The mapping use case stays sync (CPU-bound LLM prompt
construction), so there is no async instrumented mapping wrapper.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fault_mapper.domain.models import S1000DFaultDataModule
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
    ReconciliationReport,
)

if TYPE_CHECKING:
    from fault_mapper.application.async_persistence_service import (
        AsyncFaultModulePersistenceService,
    )
    from fault_mapper.application.async_reconciliation_service import (
        AsyncFaultModuleReconciliationService,
    )
    from fault_mapper.application.async_review_service import (
        AsyncFaultModuleReviewService,
    )
    from fault_mapper.domain.ports import MetricsSinkPort


def _safe_emit(fn: object, *args: object, **kwargs: object) -> None:
    """Call *fn* swallowing any exception — metrics must never break business logic."""
    try:
        fn(*args, **kwargs)  # type: ignore[operator]
    except Exception:  # noqa: BLE001
        pass


# ═══════════════════════════════════════════════════════════════════════
#  1. ASYNC PERSISTENCE SERVICE
# ═══════════════════════════════════════════════════════════════════════


class AsyncInstrumentedFaultModulePersistenceService:
    """Observability wrapper around ``AsyncFaultModulePersistenceService``."""

    def __init__(
        self,
        inner: AsyncFaultModulePersistenceService,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    async def persist(self, module: S1000DFaultDataModule) -> PersistenceResult:
        _safe_emit(self._metrics.increment, "persistence.persist.executed")
        t0 = time.monotonic()

        result = await self._inner.persist(module)

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(
            self._metrics.timing,
            "persistence.persist.duration_ms",
            duration,
        )

        if result.success:
            _safe_emit(
                self._metrics.increment,
                "persistence.persist.success",
                1,
                {"collection": result.collection},
            )
        else:
            _safe_emit(
                self._metrics.increment,
                "persistence.persist.failure",
                1,
                {"collection": result.collection},
            )

        return result

    async def retrieve(
        self,
        record_id: str,
        collection: str = "trusted",
    ) -> PersistenceEnvelope | None:
        return await self._inner.retrieve(record_id, collection)

    async def list_modules(
        self,
        collection: str = "trusted",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return await self._inner.list_modules(
            collection, limit=limit, offset=offset,
        )

    async def count_modules(self, collection: str = "trusted") -> int:
        return await self._inner.count_modules(collection)


# ═══════════════════════════════════════════════════════════════════════
#  2. ASYNC REVIEW SERVICE
# ═══════════════════════════════════════════════════════════════════════


class AsyncInstrumentedFaultModuleReviewService:
    """Observability wrapper around ``AsyncFaultModuleReviewService``."""

    def __init__(
        self,
        inner: AsyncFaultModuleReviewService,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    async def approve(
        self,
        record_id: str,
        *,
        reason: str = "",
        performed_by: str | None = None,
    ) -> PersistenceResult:
        _safe_emit(self._metrics.increment, "review.approve.executed")
        t0 = time.monotonic()

        result = await self._inner.approve(
            record_id, reason=reason, performed_by=performed_by,
        )

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(
            self._metrics.timing, "review.approve.duration_ms", duration,
        )

        if result.success:
            _safe_emit(self._metrics.increment, "review.approve.success")
        else:
            _safe_emit(self._metrics.increment, "review.approve.failure")
            if "not found" in (result.error or "").lower():
                _safe_emit(self._metrics.increment, "review.not_found")

        return result

    async def reject(
        self,
        record_id: str,
        reason: str = "",
        *,
        performed_by: str | None = None,
    ) -> PersistenceResult:
        _safe_emit(self._metrics.increment, "review.reject.executed")
        t0 = time.monotonic()

        result = await self._inner.reject(
            record_id, reason, performed_by=performed_by,
        )

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(
            self._metrics.timing, "review.reject.duration_ms", duration,
        )

        if result.success:
            _safe_emit(self._metrics.increment, "review.reject.success")
        else:
            _safe_emit(self._metrics.increment, "review.reject.failure")
            if "not found" in (result.error or "").lower():
                _safe_emit(self._metrics.increment, "review.not_found")

        return result

    async def get_review_item(
        self, record_id: str,
    ) -> PersistenceEnvelope | None:
        return await self._inner.get_review_item(record_id)

    async def list_review_items(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return await self._inner.list_review_items(limit=limit, offset=offset)

    async def count_review_items(self) -> int:
        return await self._inner.count_review_items()


# ═══════════════════════════════════════════════════════════════════════
#  3. ASYNC RECONCILIATION SERVICE
# ═══════════════════════════════════════════════════════════════════════


class AsyncInstrumentedFaultModuleReconciliationService:
    """Observability wrapper around ``AsyncFaultModuleReconciliationService``."""

    def __init__(
        self,
        inner: AsyncFaultModuleReconciliationService,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    async def sweep(
        self,
        *,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> ReconciliationReport:
        _safe_emit(
            self._metrics.increment,
            "reconciliation.sweep.executed",
            1,
            {"dry_run": str(dry_run).lower()},
        )
        t0 = time.monotonic()

        report = await self._inner.sweep(dry_run=dry_run, limit=limit)

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(
            self._metrics.timing,
            "reconciliation.sweep.duration_ms",
            duration,
        )
        _safe_emit(
            self._metrics.gauge,
            "reconciliation.duplicates_found",
            float(report.duplicates_found),
        )
        _safe_emit(
            self._metrics.gauge,
            "reconciliation.duplicates_cleaned",
            float(report.duplicates_cleaned),
        )
        _safe_emit(
            self._metrics.gauge,
            "reconciliation.duplicates_skipped",
            float(report.duplicates_skipped),
        )
        _safe_emit(
            self._metrics.gauge,
            "reconciliation.errors",
            float(report.errors),
        )

        return report

    async def find_orphaned_review_ids(self) -> list[str]:
        return await self._inner.find_orphaned_review_ids()


# ═══════════════════════════════════════════════════════════════════════
#  4. ASYNC BATCH PROCESSING SERVICE
# ═══════════════════════════════════════════════════════════════════════


class AsyncInstrumentedFaultBatchProcessingService:
    """Observability wrapper around ``AsyncFaultBatchProcessingService``.

    Metrics emitted
    ───────────────
    • ``batch.executed``          — counter
    • ``batch.duration_ms``       — timing
    • ``batch.total``             — gauge
    • ``batch.succeeded``         — gauge
    • ``batch.failed``            — gauge
    """

    def __init__(
        self,
        inner: object,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    async def process_batch(
        self,
        items: list,
    ):
        from fault_mapper.domain.value_objects import BatchReport

        _safe_emit(self._metrics.increment, "batch.executed")
        t0 = time.monotonic()

        report = await self._inner.process_batch(items)  # type: ignore[union-attr]

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(self._metrics.timing, "batch.duration_ms", duration)
        _safe_emit(self._metrics.gauge, "batch.total", float(report.total))
        _safe_emit(self._metrics.gauge, "batch.succeeded", float(report.succeeded))
        _safe_emit(self._metrics.gauge, "batch.failed", float(report.failed))

        return report
