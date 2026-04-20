"""End-to-end procedural operational flow tests (Chunk 8).

Tests the full map → validate → persist lifecycle without network,
using fake LLM/rules adapters and in-memory repository.

Covers:
  • Approved path → procedural_trusted
  • Not-reviewed path → procedural_review
  • Rejected path → not persisted
  • Result summary shape
  • Observability wiring (instrumented wrapper)
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import ReviewStatus
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.application.procedural_module_persistence_service import (
    ProceduralModulePersistenceService,
)
from fault_mapper.adapters.secondary.procedural_instrumented_services import (
    InstrumentedProceduralMappingUseCase,
    InstrumentedProceduralPersistenceService,
)
from tests.fakes.fake_fault_module_repository import FakeFaultModuleRepository


# ═══════════════════════════════════════════════════════════════════════
#  STUBS
# ═══════════════════════════════════════════════════════════════════════


class _StubProceduralUseCase:
    """Controllable stub for E2E testing."""

    def __init__(self, review_status: ReviewStatus = ReviewStatus.APPROVED):
        self._review_status = review_status

    def execute(self, source, module_type=None):
        return S1000DProceduralDataModule(
            record_id=f"E2E-{source.id}",
            review_status=self._review_status,
            mapping_version="1.0.0",
        )


class _InMemoryMetricsSink:
    """Simple metrics collector for observability tests."""

    def __init__(self):
        self.counters: dict[str, int] = {}
        self.timings: list[tuple[str, float]] = []

    def increment(self, name, value=1, tags=None):
        self.counters[name] = self.counters.get(name, 0) + (value if isinstance(value, int) else 1)

    def timing(self, name, value, tags=None):
        self.timings.append((name, value))

    def gauge(self, name, value, tags=None):
        pass


class _FailingMetricsSink:
    """Metrics sink that always raises — business logic must not break."""

    def increment(self, *a, **kw):
        raise RuntimeError("metrics boom")

    def timing(self, *a, **kw):
        raise RuntimeError("metrics boom")

    def gauge(self, *a, **kw):
        raise RuntimeError("metrics boom")


# ═══════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def repo():
    return FakeFaultModuleRepository()


def _make_source():
    """Minimal DocumentPipelineOutput stub."""
    from fault_mapper.domain.models import DocumentPipelineOutput, Metadata
    return DocumentPipelineOutput(
        id="e2e-doc-001",
        full_text="Remove the oil filter.",
        file_name="maintenance.pdf",
        file_type="pdf",
        source_path="/uploads/maintenance.pdf",
        metadata=Metadata(),
        sections=[],
        schematics=[],
    )


# ═══════════════════════════════════════════════════════════════════════
#  A. APPROVED → TRUSTED
# ═══════════════════════════════════════════════════════════════════════


class TestApprovedE2E:
    def test_approved_flows_to_trusted(self, repo):
        use_case = _StubProceduralUseCase(ReviewStatus.APPROVED)
        persistence = ProceduralModulePersistenceService(repository=repo)

        source = _make_source()
        module = use_case.execute(source)
        result = persistence.persist(module)

        assert result.success is True
        assert result.collection == "procedural_trusted"
        assert repo.count("procedural_trusted") == 1
        assert repo.count("procedural_review") == 0

    def test_result_summary_shape(self, repo):
        use_case = _StubProceduralUseCase(ReviewStatus.APPROVED)
        persistence = ProceduralModulePersistenceService(repository=repo)

        source = _make_source()
        module = use_case.execute(source)
        result = persistence.persist(module)

        # Verify all fields needed for API/CLI response
        assert result.record_id == "E2E-e2e-doc-001"
        assert result.success is True
        assert result.collection == "procedural_trusted"
        assert result.error is None
        assert module.module_type.value == "procedural"
        assert module.review_status.value == "approved"


# ═══════════════════════════════════════════════════════════════════════
#  B. NOT_REVIEWED → REVIEW
# ═══════════════════════════════════════════════════════════════════════


class TestNotReviewedE2E:
    def test_not_reviewed_flows_to_review(self, repo):
        use_case = _StubProceduralUseCase(ReviewStatus.NOT_REVIEWED)
        persistence = ProceduralModulePersistenceService(repository=repo)

        source = _make_source()
        module = use_case.execute(source)
        result = persistence.persist(module)

        assert result.success is True
        assert result.collection == "procedural_review"
        assert repo.count("procedural_trusted") == 0
        assert repo.count("procedural_review") == 1


# ═══════════════════════════════════════════════════════════════════════
#  C. REJECTED → NOT PERSISTED
# ═══════════════════════════════════════════════════════════════════════


class TestRejectedE2E:
    def test_rejected_does_not_persist(self, repo):
        use_case = _StubProceduralUseCase(ReviewStatus.REJECTED)
        persistence = ProceduralModulePersistenceService(repository=repo)

        source = _make_source()
        module = use_case.execute(source)
        result = persistence.persist(module)

        assert result.success is False
        assert repo.count("procedural_trusted") == 0
        assert repo.count("procedural_review") == 0


# ═══════════════════════════════════════════════════════════════════════
#  D. OBSERVABILITY
# ═══════════════════════════════════════════════════════════════════════


class TestObservabilityE2E:
    def test_instrumented_use_case_emits_metrics(self):
        metrics = _InMemoryMetricsSink()
        inner = _StubProceduralUseCase(ReviewStatus.APPROVED)
        wrapped = InstrumentedProceduralMappingUseCase(inner=inner, metrics=metrics)

        source = _make_source()
        module = wrapped.execute(source)

        assert metrics.counters.get("procedural.mapping.executed", 0) == 1
        assert metrics.counters.get("procedural.mapping.success", 0) == 1
        assert any(t[0] == "procedural.mapping.duration_ms" for t in metrics.timings)

    def test_instrumented_persistence_emits_metrics(self, repo):
        metrics = _InMemoryMetricsSink()
        inner = ProceduralModulePersistenceService(repository=repo)
        wrapped = InstrumentedProceduralPersistenceService(inner=inner, metrics=metrics)

        use_case = _StubProceduralUseCase(ReviewStatus.APPROVED)
        source = _make_source()
        module = use_case.execute(source)
        result = wrapped.persist(module)

        assert result.success is True
        assert metrics.counters.get("procedural.persist.executed", 0) == 1
        assert metrics.counters.get("procedural.persist.success", 0) == 1
        assert metrics.counters.get("procedural.persist.procedural_trusted", 0) == 1

    def test_failing_metrics_does_not_break_processing(self, repo):
        """Metrics sink that raises must not break business logic."""
        bad_metrics = _FailingMetricsSink()
        inner = _StubProceduralUseCase(ReviewStatus.APPROVED)
        wrapped_uc = InstrumentedProceduralMappingUseCase(inner=inner, metrics=bad_metrics)

        source = _make_source()
        module = wrapped_uc.execute(source)
        assert module.record_id == "E2E-e2e-doc-001"

        inner_persist = ProceduralModulePersistenceService(repository=repo)
        wrapped_persist = InstrumentedProceduralPersistenceService(
            inner=inner_persist, metrics=bad_metrics,
        )
        result = wrapped_persist.persist(module)
        assert result.success is True

    def test_instrumented_use_case_failure_emits_failure_metric(self):
        metrics = _InMemoryMetricsSink()

        class FailingUseCase:
            def execute(self, source, **kw):
                raise ValueError("boom")

        wrapped = InstrumentedProceduralMappingUseCase(
            inner=FailingUseCase(), metrics=metrics,
        )
        source = _make_source()
        with pytest.raises(ValueError, match="boom"):
            wrapped.execute(source)

        assert metrics.counters.get("procedural.mapping.failure", 0) == 1
