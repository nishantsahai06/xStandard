"""Tests for Chunk-14 metrics / observability wrappers.

Covers all four instrumented service wrappers:
  1. InstrumentedFaultMappingUseCase
  2. InstrumentedFaultModulePersistenceService
  3. InstrumentedFaultModuleReviewService
  4. InstrumentedFaultModuleReconciliationService

Also covers:
  - InMemoryMetricsSink adapter basics
  - MetricsSinkPort failure resilience (_safe_emit)
  - Duration/timing captured on success and failure paths
  - Dimensional tags on metrics
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.in_memory_metrics_sink import (
    InMemoryMetricsSink,
    MetricRecord,
)
from fault_mapper.adapters.secondary.instrumented_services import (
    InstrumentedFaultMappingUseCase,
    InstrumentedFaultModulePersistenceService,
    InstrumentedFaultModuleReconciliationService,
    InstrumentedFaultModuleReviewService,
    _safe_emit,
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
from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.value_objects import PersistenceEnvelope

from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository
from tests.fixtures.persistence_fixtures import (
    make_approved_module,
    make_envelope,
    make_review_required_module,
    make_schema_failed_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════


class _BrokenMetricsSink:
    """Metrics sink that raises on every method — for resilience tests."""

    def increment(self, name, value=1, tags=None):
        raise RuntimeError("Sink exploded on increment")

    def timing(self, name, duration_ms, tags=None):
        raise RuntimeError("Sink exploded on timing")

    def gauge(self, name, value, tags=None):
        raise RuntimeError("Sink exploded on gauge")


def _review_envelope(
    record_id: str = "INST-001",
    **overrides,
) -> PersistenceEnvelope:
    defaults = dict(
        record_id=record_id,
        collection="review",
        validation_status=ValidationStatus.REVIEW_REQUIRED,
        review_status=ReviewStatus.NOT_REVIEWED,
    )
    defaults.update(overrides)
    return make_envelope(**defaults)


def _orphan_scenario(repo, record_id="ORPHAN-001"):
    """Seed an orphan: same record_id in review + trusted."""
    repo.save(make_envelope(
        record_id=record_id,
        collection="trusted",
        validation_status=ValidationStatus.APPROVED,
        review_status=ReviewStatus.APPROVED,
    ))
    repo.save(make_envelope(
        record_id=record_id,
        collection="review",
        validation_status=ValidationStatus.APPROVED,
        review_status=ReviewStatus.APPROVED,
    ))


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def metrics() -> InMemoryMetricsSink:
    return InMemoryMetricsSink()


@pytest.fixture()
def repo() -> FakeFaultModuleRepository:
    return FakeFaultModuleRepository()


# ═══════════════════════════════════════════════════════════════════════
#  IN-MEMORY METRICS SINK
# ═══════════════════════════════════════════════════════════════════════


class TestInMemoryMetricsSink:
    """Basic behaviour of the in-memory metrics adapter."""

    def test_increment(self) -> None:
        sink = InMemoryMetricsSink()
        sink.increment("test.counter", 5, {"env": "prod"})
        assert len(sink.counters) == 1
        assert sink.counters[0].name == "test.counter"
        assert sink.counters[0].value == 5.0
        assert sink.counters[0].tags == {"env": "prod"}

    def test_timing(self) -> None:
        sink = InMemoryMetricsSink()
        sink.timing("test.duration", 123.45)
        assert len(sink.timings) == 1
        assert sink.timings[0].value == 123.45

    def test_gauge(self) -> None:
        sink = InMemoryMetricsSink()
        sink.gauge("test.gauge", 42.0)
        assert len(sink.gauges) == 1
        assert sink.gauges[0].value == 42.0

    def test_clear(self) -> None:
        sink = InMemoryMetricsSink()
        sink.increment("a")
        sink.timing("b", 1.0)
        sink.gauge("c", 1.0)
        sink.clear()
        assert sink.records == []

    def test_get_by_name(self) -> None:
        sink = InMemoryMetricsSink()
        sink.increment("x")
        sink.increment("y")
        sink.increment("x")
        assert len(sink.get("x")) == 2
        assert len(sink.get("y")) == 1

    def test_none_tags_become_empty_dict(self) -> None:
        sink = InMemoryMetricsSink()
        sink.increment("a")
        assert sink.records[0].tags == {}


# ═══════════════════════════════════════════════════════════════════════
#  _safe_emit RESILIENCE
# ═══════════════════════════════════════════════════════════════════════


class TestSafeEmit:
    """_safe_emit must swallow all exceptions."""

    def test_swallows_exception(self) -> None:
        def boom():
            raise RuntimeError("boom")
        _safe_emit(boom)  # should not raise

    def test_passes_args(self) -> None:
        captured = []
        def fn(*a, **kw):
            captured.append((a, kw))
        _safe_emit(fn, 1, 2, key="val")
        assert captured == [((1, 2), {"key": "val"})]


# ═══════════════════════════════════════════════════════════════════════
#  INSTRUMENTED PERSISTENCE SERVICE
# ═══════════════════════════════════════════════════════════════════════


class TestInstrumentedPersistence:
    """Metrics emitted around persist()."""

    def test_persist_success_metrics(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModulePersistenceService(repository=repo)
        svc = InstrumentedFaultModulePersistenceService(
            inner=inner, metrics=metrics,
        )
        module = make_approved_module()
        result = svc.persist(module)

        assert result.success
        assert len(metrics.get("persistence.persist.executed")) == 1
        assert len(metrics.get("persistence.persist.success")) == 1
        assert len(metrics.get("persistence.persist.failure")) == 0
        assert len(metrics.get("persistence.persist.duration_ms")) == 1

        # Check collection tag
        success_rec = metrics.get("persistence.persist.success")[0]
        assert success_rec.tags["collection"] == "trusted"

    def test_persist_review_collection_tagged(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModulePersistenceService(repository=repo)
        svc = InstrumentedFaultModulePersistenceService(
            inner=inner, metrics=metrics,
        )
        module = make_review_required_module()
        result = svc.persist(module)

        assert result.success
        success_rec = metrics.get("persistence.persist.success")[0]
        assert success_rec.tags["collection"] == "review"

    def test_persist_failure_metrics(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModulePersistenceService(repository=repo)
        svc = InstrumentedFaultModulePersistenceService(
            inner=inner, metrics=metrics,
        )
        module = make_schema_failed_module()
        result = svc.persist(module)

        assert not result.success
        assert len(metrics.get("persistence.persist.failure")) == 1

    def test_duration_is_positive(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModulePersistenceService(repository=repo)
        svc = InstrumentedFaultModulePersistenceService(
            inner=inner, metrics=metrics,
        )
        svc.persist(make_approved_module())
        timing = metrics.get("persistence.persist.duration_ms")[0]
        assert timing.value >= 0.0

    def test_delegate_read_methods(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModulePersistenceService(repository=repo)
        svc = InstrumentedFaultModulePersistenceService(
            inner=inner, metrics=metrics,
        )
        # Read-only methods should work without metrics
        assert svc.retrieve("NOPE") is None
        assert svc.list_modules() == []
        assert svc.count_modules() == 0

    def test_broken_sink_does_not_break_persist(
        self,
        repo: FakeFaultModuleRepository,
    ) -> None:
        inner = FaultModulePersistenceService(repository=repo)
        svc = InstrumentedFaultModulePersistenceService(
            inner=inner, metrics=_BrokenMetricsSink(),
        )
        module = make_approved_module()
        result = svc.persist(module)
        assert result.success  # business outcome unaffected


# ═══════════════════════════════════════════════════════════════════════
#  INSTRUMENTED REVIEW SERVICE
# ═══════════════════════════════════════════════════════════════════════


class TestInstrumentedReview:
    """Metrics emitted around approve() and reject()."""

    def test_approve_success_metrics(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        repo.save(_review_envelope())
        inner = FaultModuleReviewService(repository=repo)
        svc = InstrumentedFaultModuleReviewService(
            inner=inner, metrics=metrics,
        )
        result = svc.approve("INST-001")

        assert result.success
        assert len(metrics.get("review.approve.executed")) == 1
        assert len(metrics.get("review.approve.success")) == 1
        assert len(metrics.get("review.approve.failure")) == 0
        assert len(metrics.get("review.approve.duration_ms")) == 1

    def test_approve_missing_emits_not_found(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModuleReviewService(repository=repo)
        svc = InstrumentedFaultModuleReviewService(
            inner=inner, metrics=metrics,
        )
        result = svc.approve("NOPE")

        assert not result.success
        assert len(metrics.get("review.approve.failure")) == 1
        assert len(metrics.get("review.not_found")) == 1

    def test_reject_success_metrics(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        repo.save(_review_envelope())
        inner = FaultModuleReviewService(repository=repo)
        svc = InstrumentedFaultModuleReviewService(
            inner=inner, metrics=metrics,
        )
        result = svc.reject("INST-001", reason="Bad data")

        assert result.success
        assert len(metrics.get("review.reject.executed")) == 1
        assert len(metrics.get("review.reject.success")) == 1
        assert len(metrics.get("review.reject.duration_ms")) == 1

    def test_reject_missing_emits_not_found(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModuleReviewService(repository=repo)
        svc = InstrumentedFaultModuleReviewService(
            inner=inner, metrics=metrics,
        )
        result = svc.reject("NOPE")

        assert not result.success
        assert len(metrics.get("review.reject.failure")) == 1
        assert len(metrics.get("review.not_found")) == 1

    def test_delegate_read_methods(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModuleReviewService(repository=repo)
        svc = InstrumentedFaultModuleReviewService(
            inner=inner, metrics=metrics,
        )
        assert svc.get_review_item("X") is None
        assert svc.list_review_items() == []
        assert svc.count_review_items() == 0

    def test_broken_sink_does_not_break_approve(
        self,
        repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(_review_envelope())
        inner = FaultModuleReviewService(repository=repo)
        svc = InstrumentedFaultModuleReviewService(
            inner=inner, metrics=_BrokenMetricsSink(),
        )
        result = svc.approve("INST-001")
        assert result.success

    def test_broken_sink_does_not_break_reject(
        self,
        repo: FakeFaultModuleRepository,
    ) -> None:
        repo.save(_review_envelope())
        inner = FaultModuleReviewService(repository=repo)
        svc = InstrumentedFaultModuleReviewService(
            inner=inner, metrics=_BrokenMetricsSink(),
        )
        result = svc.reject("INST-001")
        assert result.success


# ═══════════════════════════════════════════════════════════════════════
#  INSTRUMENTED RECONCILIATION SERVICE
# ═══════════════════════════════════════════════════════════════════════


class TestInstrumentedReconciliation:
    """Metrics emitted around sweep()."""

    def test_sweep_empty_metrics(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModuleReconciliationService(repository=repo)
        svc = InstrumentedFaultModuleReconciliationService(
            inner=inner, metrics=metrics,
        )
        report = svc.sweep()

        assert report.total_review_scanned == 0
        assert len(metrics.get("reconciliation.sweep.executed")) == 1
        assert len(metrics.get("reconciliation.sweep.duration_ms")) == 1

        # Gauges should be 0
        found = metrics.get("reconciliation.duplicates_found")
        assert len(found) == 1
        assert found[0].value == 0.0

    def test_sweep_with_orphan_metrics(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        _orphan_scenario(repo)
        inner = FaultModuleReconciliationService(repository=repo)
        svc = InstrumentedFaultModuleReconciliationService(
            inner=inner, metrics=metrics,
        )
        report = svc.sweep()

        assert report.duplicates_cleaned == 1
        cleaned = metrics.get("reconciliation.duplicates_cleaned")
        assert cleaned[0].value == 1.0

    def test_dry_run_tag(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModuleReconciliationService(repository=repo)
        svc = InstrumentedFaultModuleReconciliationService(
            inner=inner, metrics=metrics,
        )
        svc.sweep(dry_run=True)

        executed = metrics.get("reconciliation.sweep.executed")[0]
        assert executed.tags["dry_run"] == "true"

    def test_delegate_find_orphaned(
        self,
        repo: FakeFaultModuleRepository,
        metrics: InMemoryMetricsSink,
    ) -> None:
        inner = FaultModuleReconciliationService(repository=repo)
        svc = InstrumentedFaultModuleReconciliationService(
            inner=inner, metrics=metrics,
        )
        assert svc.find_orphaned_review_ids() == []

    def test_broken_sink_does_not_break_sweep(
        self,
        repo: FakeFaultModuleRepository,
    ) -> None:
        _orphan_scenario(repo)
        inner = FaultModuleReconciliationService(repository=repo)
        svc = InstrumentedFaultModuleReconciliationService(
            inner=inner, metrics=_BrokenMetricsSink(),
        )
        report = svc.sweep()
        assert report.duplicates_cleaned == 1  # business result intact


# ═══════════════════════════════════════════════════════════════════════
#  INSTRUMENTED MAPPING USE CASE (stub-based)
# ═══════════════════════════════════════════════════════════════════════


class _StubMappingResult:
    """Minimal stub to represent a mapped module."""

    def __init__(self, status=ValidationStatus.APPROVED):
        self.validation_status = status


class _StubMappingUseCase:
    """Stub that returns a fake result without real pipeline deps."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        result_status: ValidationStatus = ValidationStatus.APPROVED,
    ) -> None:
        self._should_fail = should_fail
        self._result_status = result_status

    def execute(self, source):
        if self._should_fail:
            raise ValueError("No fault-relevant sections found")
        return _StubMappingResult(status=self._result_status)


class TestInstrumentedMapping:
    """Metrics emitted around execute()."""

    def test_success_metrics(
        self,
        metrics: InMemoryMetricsSink,
    ) -> None:
        stub = _StubMappingUseCase()
        svc = InstrumentedFaultMappingUseCase(inner=stub, metrics=metrics)
        result = svc.execute(None)

        assert result.validation_status == ValidationStatus.APPROVED
        assert len(metrics.get("mapping.executed")) == 1
        assert len(metrics.get("mapping.success")) == 1
        assert len(metrics.get("mapping.failure")) == 0
        assert len(metrics.get("mapping.duration_ms")) == 1

    def test_validation_status_counter(
        self,
        metrics: InMemoryMetricsSink,
    ) -> None:
        stub = _StubMappingUseCase(
            result_status=ValidationStatus.REVIEW_REQUIRED,
        )
        svc = InstrumentedFaultMappingUseCase(inner=stub, metrics=metrics)
        svc.execute(None)

        status_metrics = metrics.get("mapping.validation.review_required")
        assert len(status_metrics) == 1
        assert status_metrics[0].tags["status"] == "review_required"

    def test_failure_metrics(
        self,
        metrics: InMemoryMetricsSink,
    ) -> None:
        stub = _StubMappingUseCase(should_fail=True)
        svc = InstrumentedFaultMappingUseCase(inner=stub, metrics=metrics)

        with pytest.raises(ValueError, match="No fault-relevant"):
            svc.execute(None)

        assert len(metrics.get("mapping.executed")) == 1
        assert len(metrics.get("mapping.failure")) == 1
        assert len(metrics.get("mapping.success")) == 0
        assert len(metrics.get("mapping.duration_ms")) == 1

    def test_duration_captured_on_failure(
        self,
        metrics: InMemoryMetricsSink,
    ) -> None:
        stub = _StubMappingUseCase(should_fail=True)
        svc = InstrumentedFaultMappingUseCase(inner=stub, metrics=metrics)

        with pytest.raises(ValueError):
            svc.execute(None)

        timing = metrics.get("mapping.duration_ms")[0]
        assert timing.value >= 0.0

    def test_broken_sink_does_not_break_mapping(self) -> None:
        stub = _StubMappingUseCase()
        svc = InstrumentedFaultMappingUseCase(
            inner=stub, metrics=_BrokenMetricsSink(),
        )
        result = svc.execute(None)
        assert result.validation_status == ValidationStatus.APPROVED

    def test_broken_sink_does_not_suppress_failure(self) -> None:
        stub = _StubMappingUseCase(should_fail=True)
        svc = InstrumentedFaultMappingUseCase(
            inner=stub, metrics=_BrokenMetricsSink(),
        )
        with pytest.raises(ValueError):
            svc.execute(None)
