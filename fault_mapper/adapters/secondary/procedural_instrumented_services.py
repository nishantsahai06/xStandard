"""Instrumented wrappers for procedural application services.

Mirrors ``instrumented_services.py`` but wraps procedural services.
Only covers the top-level process flow (use case + persistence)
as specified by Chunk 8 scope.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.domain.value_objects import (
    PersistenceEnvelope,
    PersistenceResult,
)

if TYPE_CHECKING:
    from fault_mapper.application.procedural_mapping_use_case import (
        ProceduralMappingUseCase,
    )
    from fault_mapper.application.procedural_module_persistence_service import (
        ProceduralModulePersistenceService,
    )
    from fault_mapper.domain.ports import MetricsSinkPort


def _safe_emit(fn: object, *args: object, **kwargs: object) -> None:
    """Call *fn* swallowing any exception — metrics must never break business logic."""
    try:
        fn(*args, **kwargs)  # type: ignore[operator]
    except Exception:  # noqa: BLE001
        pass


# ═══════════════════════════════════════════════════════════════════════
#  1. PROCEDURAL MAPPING USE CASE
# ═══════════════════════════════════════════════════════════════════════


class InstrumentedProceduralMappingUseCase:
    """Observability wrapper around ``ProceduralMappingUseCase``.

    Metrics emitted
    ───────────────
    • ``procedural.mapping.executed``    — counter, +1 per call
    • ``procedural.mapping.success``     — counter, +1 on success
    • ``procedural.mapping.failure``     — counter, +1 on exception
    • ``procedural.mapping.duration_ms`` — timing
    """

    def __init__(
        self,
        inner: ProceduralMappingUseCase,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    def execute(self, source, module_type=None):
        _safe_emit(self._metrics.increment, "procedural.mapping.executed")
        t0 = time.monotonic()
        kwargs = {}
        if module_type is not None:
            kwargs["module_type"] = module_type
        try:
            module = self._inner.execute(source, **kwargs)
        except Exception:
            duration = (time.monotonic() - t0) * 1000
            _safe_emit(self._metrics.increment, "procedural.mapping.failure")
            _safe_emit(self._metrics.timing, "procedural.mapping.duration_ms", duration)
            raise

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(self._metrics.increment, "procedural.mapping.success")
        _safe_emit(self._metrics.timing, "procedural.mapping.duration_ms", duration)

        review_tag = module.review_status.value
        _safe_emit(
            self._metrics.increment,
            f"procedural.mapping.review.{review_tag}",
            1,
            {"review_status": review_tag},
        )

        return module


# ═══════════════════════════════════════════════════════════════════════
#  2. PROCEDURAL PERSISTENCE SERVICE
# ═══════════════════════════════════════════════════════════════════════


class InstrumentedProceduralPersistenceService:
    """Observability wrapper around ``ProceduralModulePersistenceService``.

    Metrics emitted
    ───────────────
    • ``procedural.persist.executed``    — counter
    • ``procedural.persist.success``     — counter
    • ``procedural.persist.failure``     — counter
    • ``procedural.persist.duration_ms`` — timing
    • ``procedural.persist.<collection>`` — counter per target collection
    """

    def __init__(
        self,
        inner: ProceduralModulePersistenceService,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    def persist(self, module) -> PersistenceResult:
        _safe_emit(self._metrics.increment, "procedural.persist.executed")
        t0 = time.monotonic()
        try:
            result = self._inner.persist(module)
        except Exception:
            duration = (time.monotonic() - t0) * 1000
            _safe_emit(self._metrics.increment, "procedural.persist.failure")
            _safe_emit(self._metrics.timing, "procedural.persist.duration_ms", duration)
            raise

        duration = (time.monotonic() - t0) * 1000
        if result.success:
            _safe_emit(self._metrics.increment, "procedural.persist.success")
            _safe_emit(
                self._metrics.increment,
                f"procedural.persist.{result.collection}",
            )
        else:
            _safe_emit(self._metrics.increment, "procedural.persist.failure")
        _safe_emit(self._metrics.timing, "procedural.persist.duration_ms", duration)
        return result

    def retrieve(self, record_id, collection="procedural_trusted"):
        return self._inner.retrieve(record_id, collection)

    def list_modules(self, collection="procedural_trusted", *, limit=100, offset=0):
        return self._inner.list_modules(collection, limit=limit, offset=offset)

    def count_modules(self, collection="procedural_trusted"):
        return self._inner.count_modules(collection)


# ═══════════════════════════════════════════════════════════════════════
#  3. PROCEDURAL BATCH PROCESSING SERVICE (SYNC)
# ═══════════════════════════════════════════════════════════════════════


class InstrumentedProceduralBatchProcessingService:
    """Observability wrapper around ``ProceduralBatchProcessingService``.

    Metrics emitted
    ───────────────
    • ``procedural.batch.executed``    — counter
    • ``procedural.batch.duration_ms`` — timing
    • ``procedural.batch.total``       — gauge
    • ``procedural.batch.succeeded``   — gauge
    • ``procedural.batch.failed``      — gauge
    """

    def __init__(
        self,
        inner: object,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    def process_batch(self, items: list):
        from fault_mapper.domain.value_objects import BatchReport

        _safe_emit(self._metrics.increment, "procedural.batch.executed")
        t0 = time.monotonic()

        report = self._inner.process_batch(items)  # type: ignore[union-attr]

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(self._metrics.timing, "procedural.batch.duration_ms", duration)
        _safe_emit(self._metrics.gauge, "procedural.batch.total", float(report.total))
        _safe_emit(self._metrics.gauge, "procedural.batch.succeeded", float(report.succeeded))
        _safe_emit(self._metrics.gauge, "procedural.batch.failed", float(report.failed))

        return report


# ═══════════════════════════════════════════════════════════════════════
#  4. PROCEDURAL BATCH PROCESSING SERVICE (ASYNC)
# ═══════════════════════════════════════════════════════════════════════


class AsyncInstrumentedProceduralBatchProcessingService:
    """Async observability wrapper around ``AsyncProceduralBatchProcessingService``.

    Metrics emitted
    ───────────────
    • ``procedural.batch.executed``    — counter
    • ``procedural.batch.duration_ms`` — timing
    • ``procedural.batch.total``       — gauge
    • ``procedural.batch.succeeded``   — gauge
    • ``procedural.batch.failed``      — gauge
    """

    def __init__(
        self,
        inner: object,
        metrics: MetricsSinkPort,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    async def process_batch(self, items: list):
        from fault_mapper.domain.value_objects import BatchReport

        _safe_emit(self._metrics.increment, "procedural.batch.executed")
        t0 = time.monotonic()

        report = await self._inner.process_batch(items)  # type: ignore[union-attr]

        duration = (time.monotonic() - t0) * 1000
        _safe_emit(self._metrics.timing, "procedural.batch.duration_ms", duration)
        _safe_emit(self._metrics.gauge, "procedural.batch.total", float(report.total))
        _safe_emit(self._metrics.gauge, "procedural.batch.succeeded", float(report.succeeded))
        _safe_emit(self._metrics.gauge, "procedural.batch.failed", float(report.failed))

        return report
