"""Procedural service provider — dependency wiring for procedural entry points.

Mirrors ``ServiceProvider`` structurally but holds procedural services.
Kept separate to avoid bloating the fault service provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fault_mapper.application.procedural_mapping_use_case import (
    ProceduralMappingUseCase,
)
from fault_mapper.application.procedural_module_persistence_service import (
    ProceduralModulePersistenceService,
)
from fault_mapper.domain.ports import (
    FaultModuleRepositoryPort,
    MetricsSinkPort,
)
from fault_mapper.infrastructure.procedural_config import ProceduralAppConfig
from fault_mapper.infrastructure.procedural_factory import ProceduralMapperFactory


@dataclass
class ProceduralServiceProvider:
    """Holds the fully-wired procedural service instances.

    The ``use_case`` is optional — processing requires an LLM client.
    The ``batch`` is optional — requires an LLM client.
    """

    use_case: ProceduralMappingUseCase | None
    persistence: ProceduralModulePersistenceService
    batch: Any | None = None


def build_procedural_services(
    *,
    config: ProceduralAppConfig | None = None,
    llm_client: Any = None,
    repository: FaultModuleRepositoryPort | None = None,
    metrics_sink: MetricsSinkPort | None = None,
) -> ProceduralServiceProvider:
    """Build a ``ProceduralServiceProvider`` from config.

    Parameters
    ----------
    config
        Procedural-specific configuration.  Defaults if None.
    llm_client
        LLM callable (required for the mapping use case).
    repository
        Injected repository; defaults to in-memory.
    metrics_sink
        Optional metrics sink for instrumentation.

    Returns
    -------
    ProceduralServiceProvider
        Ready for injection into API or CLI.
    """
    if config is None:
        config = ProceduralAppConfig()

    factory = ProceduralMapperFactory(
        config=config,
        llm_client=llm_client or (lambda: None),
        repository=repository,
    )

    # Use case requires real LLM client
    use_case: ProceduralMappingUseCase | None = None
    if llm_client is not None:
        use_case = factory.create_use_case()

    persistence = factory.create_persistence_service()

    # Wrap with instrumentation if metrics sink provided
    if metrics_sink is not None:
        from fault_mapper.adapters.secondary.procedural_instrumented_services import (
            InstrumentedProceduralPersistenceService,
        )
        persistence = InstrumentedProceduralPersistenceService(
            inner=persistence,
            metrics=metrics_sink,
        )
        if use_case is not None:
            from fault_mapper.adapters.secondary.procedural_instrumented_services import (
                InstrumentedProceduralMappingUseCase,
            )
            use_case = InstrumentedProceduralMappingUseCase(
                inner=use_case,
                metrics=metrics_sink,
            )

    # ── Batch service (requires LLM) ────────────────────────────
    batch: Any = None
    if llm_client is not None:
        from fault_mapper.application.procedural_batch_processing_service import (
            ProceduralBatchProcessingService,
        )
        batch = ProceduralBatchProcessingService(
            use_case=use_case if use_case is not None else factory.create_use_case(),
            persistence=persistence,
        )
        if metrics_sink is not None:
            from fault_mapper.adapters.secondary.procedural_instrumented_services import (
                InstrumentedProceduralBatchProcessingService,
            )
            batch = InstrumentedProceduralBatchProcessingService(
                inner=batch, metrics=metrics_sink,
            )

    return ProceduralServiceProvider(
        use_case=use_case,
        persistence=persistence,
        batch=batch,
    )
