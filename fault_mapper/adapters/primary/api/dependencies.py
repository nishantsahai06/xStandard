"""Service provider for the API / CLI entry points.

Encapsulates the ``FaultMapperFactory`` wiring so that API routes
and CLI commands receive fully-constructed services without knowing
about factory internals.

For **testing**, callers can inject a pre-built ``ServiceProvider``
or ``AsyncServiceProvider`` with fakes / stubs.  For **production**,
call ``build_services()`` or ``build_async_services()`` which read
config and wire real adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fault_mapper.application.fault_mapping_use_case import FaultMappingUseCase
from fault_mapper.application.fault_module_persistence_service import (
    FaultModulePersistenceService,
)
from fault_mapper.application.fault_module_reconciliation_service import (
    FaultModuleReconciliationService,
)
from fault_mapper.application.fault_module_review_service import (
    FaultModuleReviewService,
)
from fault_mapper.domain.ports import (
    AsyncAuditRepositoryPort,
    AsyncFaultModuleRepositoryPort,
    AuditRepositoryPort,
    FaultModuleRepositoryPort,
    MetricsSinkPort,
)
from fault_mapper.infrastructure.config import AppConfig
from fault_mapper.infrastructure.factory import FaultMapperFactory


@dataclass
class ServiceProvider:
    """Holds the fully-wired service instances used by API / CLI.

    The ``use_case`` is optional — processing requires an LLM client,
    which may not be available in all deployments (e.g. review-only
    instances).
    """

    use_case: FaultMappingUseCase | None
    persistence: FaultModulePersistenceService
    review: FaultModuleReviewService
    reconciliation: FaultModuleReconciliationService
    batch: Any = None  # FaultBatchProcessingService (or instrumented)


@dataclass
class AsyncServiceProvider:
    """Holds the fully-wired *async* service instances used by API / CLI.

    The ``use_case`` remains sync (CPU-bound LLM prompt construction).
    Persistence, review, and reconciliation are async.
    """

    use_case: FaultMappingUseCase | None
    persistence: Any  # AsyncFaultModulePersistenceService (or instrumented)
    review: Any       # AsyncFaultModuleReviewService (or instrumented)
    reconciliation: Any  # AsyncFaultModuleReconciliationService (or instrumented)
    batch: Any = None  # AsyncFaultBatchProcessingService (or instrumented)


def build_services(
    *,
    config: AppConfig | None = None,
    llm_client: Any = None,
    repository: FaultModuleRepositoryPort | None = None,
    audit_repo: AuditRepositoryPort | None = None,
    metrics_sink: MetricsSinkPort | None = None,
) -> ServiceProvider:
    """Build a ``ServiceProvider`` from config.

    Parameters
    ----------
    config
        App-wide configuration.  Defaults if None.
    llm_client
        LLM callable (required for the mapping use case).
    repository
        Injected repository; defaults to in-memory.
    audit_repo
        Optional audit repository.
    metrics_sink
        Optional metrics sink for instrumentation.

    Returns
    -------
    ServiceProvider
        Ready for injection into API or CLI.
    """
    if config is None:
        config = AppConfig()

    factory = FaultMapperFactory(
        config=config,
        llm_client=llm_client,
        repository=repository,
        audit_repo=audit_repo,
        metrics_sink=metrics_sink,
    )

    # Use case is optional — requires LLM client
    use_case: FaultMappingUseCase | None = None
    if llm_client is not None:
        use_case = factory.create_use_case()

    # Batch service is optional — requires LLM client
    batch = None
    if llm_client is not None:
        batch = factory.create_batch_processing_service()

    return ServiceProvider(
        use_case=use_case,
        persistence=factory.create_persistence_service(),
        review=factory.create_review_service(),
        reconciliation=factory.create_reconciliation_service(),
        batch=batch,
    )


def build_async_services(
    *,
    config: AppConfig | None = None,
    llm_client: Any = None,
    async_repository: AsyncFaultModuleRepositoryPort | None = None,
    async_audit_repo: AsyncAuditRepositoryPort | None = None,
    metrics_sink: MetricsSinkPort | None = None,
) -> AsyncServiceProvider:
    """Build an ``AsyncServiceProvider`` from config.

    Parameters
    ----------
    config
        App-wide configuration.  Defaults if None.
    llm_client
        LLM callable (required for the mapping use case).
    async_repository
        Injected async repository; defaults to async in-memory.
    async_audit_repo
        Optional async audit repository.
    metrics_sink
        Optional metrics sink for instrumentation.

    Returns
    -------
    AsyncServiceProvider
        Ready for injection into async API or CLI bridge.
    """
    if config is None:
        config = AppConfig()

    factory = FaultMapperFactory(
        config=config,
        llm_client=llm_client,
        async_repository=async_repository,
        async_audit_repo=async_audit_repo,
        metrics_sink=metrics_sink,
    )

    use_case: FaultMappingUseCase | None = None
    if llm_client is not None:
        use_case = factory.create_use_case()

    # Batch service is optional — requires LLM client
    batch = None
    if llm_client is not None:
        batch = factory.create_async_batch_processing_service()

    return AsyncServiceProvider(
        use_case=use_case,
        persistence=factory.create_async_persistence_service(),
        review=factory.create_async_review_service(),
        reconciliation=factory.create_async_reconciliation_service(),
        batch=batch,
    )
