"""Instrumented service wrappers — observability via delegation.

Each wrapper class delegates to a real service instance and emits
metrics around every public method call.  The wrappers are transparent:
they preserve exact return types and exception semantics.

Design principles
─────────────────
• **Decorator pattern** — each wrapper has the same public API as the
  service it wraps.  Calling code cannot tell the difference.
• **Metrics are best-effort** — if the ``MetricsSinkPort`` raises,
  the error is swallowed and the business result is returned unchanged.
• **Duration is always captured** — even on failure paths, so that
  latency outliers are visible.
• **Tags carry dimensionality** — ``status``, ``collection``,
  ``outcome``, ``record_id`` where appropriate.

Wrapper inventory
─────────────────
1. ``InstrumentedFaultMappingUseCase``
2. ``InstrumentedFaultModulePersistenceService``
3. ``InstrumentedFaultModuleReviewService``
4. ``InstrumentedFaultModuleReconciliationService``
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fault_mapper.domain.models import (
    DocumentPipelineOutput,
    S1000DFaultDataModule,
)
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
    ReconciliationReport,
)

if TYPE_CHECKING:
    from fault_mapper.application.fault_mapping_use_case import (
        FaultMappingUseCase,
    )
    from fault_mapper.application.fault_module_persistence_service import (
        FaultModulePersistenceService,
    )
    from fault_mapper.application.fault_module_reconciliation_service import (
        FaultModuleReconciliationService,
    )
    from fault_mapper.application.fault_module_review_service import (
        FaultModuleReviewService,
    )
    from fault_mapper.domain.ports import MetricsSinkPort


def _safe_emit(fn: object, *args: object, **kwargs: object) -> None:  # noqa: ANN401
    """Call *fn* swallowing any exception — metrics must never break business logic."""
    try:
        fn(*args, **kwargs)  # type: ignore[operator]
    except Exception:  # noqa: BLE001
        pass


# ═══════════════════════════════════════════════════════════════════════
#  1. MAPPING USE CASE
# ═══════════════════════════════════════════════════════════════════════


class InstrumentedFaultMappingUseCase:
    """Observability wrapper around ``FaultMappingUseCase``.

    Metrics emitted
    ───────────────
    • ``mapping.executed``        — counter, +1 per call
    • ``mapping.success``         — counter, +1 on success
    • ``mapping.failure``         — counter, +1 on exception
    • ``mapping.duration_ms``     — timing
    • ``mapping.validation.<status>`` — counter per validation_status
    """

    def __init__(
        self,
        inner: FaultMappingUseCase,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    def execute(
        self,
        source: DocumentPipelineOutput,
    ) -> S1000DFaultDataModule:
        _safe_emit(self._metrics.increment, "mapping.executed")
        t0 = time.monotonic()
        try:
            module = self._inner.execute(source)
        except Exception:
            duration = (time.monotonic() - t0) * 1000
            _safe_emit(self._metrics.increment, "mapping.failure")
            _safe_emit(self._metrics.timing, "mapping.duration_ms", duration)
            raise

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(self._metrics.increment, "mapping.success")
        _safe_emit(self._metrics.timing, "mapping.duration_ms", duration)

        # Emit per-validation-status counter
        status_tag = module.validation_status.value
        _safe_emit(
            self._metrics.increment,
            f"mapping.validation.{status_tag}",
            1,
            {"status": status_tag},
        )

        return module


# ═══════════════════════════════════════════════════════════════════════
#  2. PERSISTENCE SERVICE
# ═══════════════════════════════════════════════════════════════════════


class InstrumentedFaultModulePersistenceService:
    """Observability wrapper around ``FaultModulePersistenceService``.

    Metrics emitted
    ───────────────
    • ``persistence.persist.executed``   — counter
    • ``persistence.persist.success``    — counter (tags: collection)
    • ``persistence.persist.failure``    — counter (tags: collection)
    • ``persistence.persist.duration_ms``— timing
    """

    def __init__(
        self,
        inner: FaultModulePersistenceService,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    def persist(self, module: S1000DFaultDataModule) -> PersistenceResult:
        _safe_emit(self._metrics.increment, "persistence.persist.executed")
        t0 = time.monotonic()

        result = self._inner.persist(module)

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

    # ── Delegate read-only methods without instrumentation ───────

    def retrieve(
        self,
        record_id: str,
        collection: str = "trusted",
    ) -> PersistenceEnvelope | None:
        return self._inner.retrieve(record_id, collection)

    def list_modules(
        self,
        collection: str = "trusted",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return self._inner.list_modules(collection, limit=limit, offset=offset)

    def count_modules(self, collection: str = "trusted") -> int:
        return self._inner.count_modules(collection)


# ═══════════════════════════════════════════════════════════════════════
#  3. REVIEW SERVICE
# ═══════════════════════════════════════════════════════════════════════


class InstrumentedFaultModuleReviewService:
    """Observability wrapper around ``FaultModuleReviewService``.

    Metrics emitted
    ───────────────
    • ``review.approve.executed``    — counter
    • ``review.approve.success``     — counter
    • ``review.approve.failure``     — counter
    • ``review.approve.duration_ms`` — timing
    • ``review.reject.executed``     — counter
    • ``review.reject.success``      — counter
    • ``review.reject.failure``      — counter
    • ``review.reject.duration_ms``  — timing
    • ``review.not_found``           — counter (approve or reject miss)
    """

    def __init__(
        self,
        inner: FaultModuleReviewService,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    def approve(
        self,
        record_id: str,
        *,
        reason: str = "",
        performed_by: str | None = None,
    ) -> PersistenceResult:
        _safe_emit(self._metrics.increment, "review.approve.executed")
        t0 = time.monotonic()

        result = self._inner.approve(
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

    def reject(
        self,
        record_id: str,
        reason: str = "",
        *,
        performed_by: str | None = None,
    ) -> PersistenceResult:
        _safe_emit(self._metrics.increment, "review.reject.executed")
        t0 = time.monotonic()

        result = self._inner.reject(
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

    # ── Delegate read-only methods without instrumentation ───────

    def get_review_item(self, record_id: str) -> PersistenceEnvelope | None:
        return self._inner.get_review_item(record_id)

    def list_review_items(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        return self._inner.list_review_items(limit=limit, offset=offset)

    def count_review_items(self) -> int:
        return self._inner.count_review_items()


# ═══════════════════════════════════════════════════════════════════════
#  4. RECONCILIATION SERVICE
# ═══════════════════════════════════════════════════════════════════════


class InstrumentedFaultModuleReconciliationService:
    """Observability wrapper around ``FaultModuleReconciliationService``.

    Metrics emitted
    ───────────────
    • ``reconciliation.sweep.executed``      — counter
    • ``reconciliation.sweep.duration_ms``   — timing
    • ``reconciliation.duplicates_found``    — gauge
    • ``reconciliation.duplicates_cleaned``  — gauge
    • ``reconciliation.duplicates_skipped``  — gauge
    • ``reconciliation.errors``              — gauge
    """

    def __init__(
        self,
        inner: FaultModuleReconciliationService,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    def sweep(
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

        report = self._inner.sweep(dry_run=dry_run, limit=limit)

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

    def find_orphaned_review_ids(self) -> list[str]:
        return self._inner.find_orphaned_review_ids()


# ═══════════════════════════════════════════════════════════════════════
#  5. BATCH PROCESSING SERVICE
# ═══════════════════════════════════════════════════════════════════════


class InstrumentedFaultBatchProcessingService:
    """Observability wrapper around ``FaultBatchProcessingService``.

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

    def process_batch(
        self,
        items: list,
    ):
        from fault_mapper.domain.value_objects import BatchReport

        _safe_emit(self._metrics.increment, "batch.executed")
        t0 = time.monotonic()

        report = self._inner.process_batch(items)  # type: ignore[union-attr]

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(self._metrics.timing, "batch.duration_ms", duration)
        _safe_emit(self._metrics.gauge, "batch.total", float(report.total))
        _safe_emit(self._metrics.gauge, "batch.succeeded", float(report.succeeded))
        _safe_emit(self._metrics.gauge, "batch.failed", float(report.failed))

        return report
