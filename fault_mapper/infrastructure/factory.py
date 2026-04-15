"""Dependency-injection factory -- wires the full object graph.

This is the COMPOSITION ROOT of the application.  It is the only module
that knows about concrete adapter classes.  Everything else depends only
on domain ports (protocols).

Two entry points:
1. FaultMapperFactory(config).create_use_case()  -- OOP style
2. build_fault_mapper(config, llm_client)         -- functional shortcut

Both return a fully wired FaultMappingUseCase ready for
use_case.execute(source).

Persistence:
  create_persistence_service()  -- returns wired FaultModulePersistenceService
  The persistence service is intentionally SEPARATE from the use case
  so that callers can persist modules after mapping + validation:

      module = use_case.execute(source)
      result = persistence_service.persist(module)

LLM client injection:
The caller (CLI, web handler, test harness) is responsible for
constructing the LLM client and passing it in.  This factory does NOT
read API keys or create HTTP clients -- that is the caller concern.

If llm_client is None the factory raises ValueError at create_use_case
time (fail-fast, not fail-silent).
"""

from __future__ import annotations

from typing import Any

from fault_mapper.infrastructure.config import AppConfig, MappingConfig, MongoConfig

# Adapter imports (infrastructure is the ONLY layer that may do this)
from fault_mapper.adapters.secondary.llm_interpreter_adapter import (
    LlmInterpreterAdapter,
)
from fault_mapper.adapters.secondary.rules_adapter import RulesAdapter

# Validation / review-gate adapter imports
from fault_mapper.adapters.secondary.schema_validator import (
    validate_against_schema,
)
from fault_mapper.adapters.secondary.structural_validator import (
    validate_structure,
)
from fault_mapper.adapters.secondary.business_rule_validator import (
    validate_business_rules,
)
from fault_mapper.adapters.secondary.review_gate import default_review_gate

# Persistence adapter imports
from fault_mapper.adapters.secondary.in_memory_repository import (
    InMemoryFaultModuleRepository,
)

# Application-layer imports
from fault_mapper.application.fault_mapping_use_case import FaultMappingUseCase
from fault_mapper.application.fault_section_selector import FaultSectionSelector
from fault_mapper.application.fault_mode_router import FaultModeRouter
from fault_mapper.application.fault_header_builder import FaultHeaderBuilder
from fault_mapper.application.fault_reporting_mapper import FaultReportingMapper
from fault_mapper.application.fault_isolation_mapper import FaultIsolationMapper
from fault_mapper.application.fault_table_classifier import FaultTableClassifier
from fault_mapper.application.fault_schematic_correlator import (
    FaultSchematicCorrelator,
)
from fault_mapper.application.fault_module_assembler import FaultModuleAssembler
from fault_mapper.application.fault_module_validator import FaultModuleValidator
from fault_mapper.application.fault_module_persistence_service import (
    FaultModulePersistenceService,
)
from fault_mapper.application.fault_module_review_service import (
    FaultModuleReviewService,
)
from fault_mapper.application.fault_module_reconciliation_service import (
    FaultModuleReconciliationService,
)

# Domain port for optional review policy
from fault_mapper.domain.ports import (
    AsyncAuditRepositoryPort,
    AsyncFaultModuleRepositoryPort,
    AuditRepositoryPort,
    FaultModuleRepositoryPort,
    MappingReviewPolicyPort,
    MetricsSinkPort,
    TrustedModuleHandoffPort,
)


class FaultMapperFactory:
    """Composition root -- builds the fully wired use case and persistence.

    Accepts an AppConfig and an LLM client callable, and produces
    a ready-to-use FaultMappingUseCase with all dependencies injected.
    Optionally also creates a FaultModulePersistenceService.
    """

    def __init__(
        self,
        config: AppConfig,
        llm_client: Any = None,
        review_policy: MappingReviewPolicyPort | None = None,
        repository: FaultModuleRepositoryPort | None = None,
        handoff: TrustedModuleHandoffPort | None = None,
        audit_repo: AuditRepositoryPort | None = None,
        metrics_sink: MetricsSinkPort | None = None,
        async_repository: AsyncFaultModuleRepositoryPort | None = None,
        async_audit_repo: AsyncAuditRepositoryPort | None = None,
    ) -> None:
        self._config = config
        self._llm_client = llm_client
        self._review_policy = review_policy
        self._repository = repository
        self._handoff = handoff
        self._audit_repo = audit_repo
        self._metrics_sink = metrics_sink
        self._async_repository = async_repository
        self._async_audit_repo = async_audit_repo

    def create_use_case(self) -> FaultMappingUseCase:
        """Wire all dependencies and return the top-level use case.

        Returns
        -------
        FaultMappingUseCase
            Fully wired, ready to call execute(source).

        Raises
        ------
        ValueError
            If llm_client is None (cannot build LLM adapter).
        """
        if self._llm_client is None:
            raise ValueError(
                "Cannot build FaultMappingUseCase without an LLM client. "
                "Pass a callable with the OpenAI chat-completions shape."
            )

        # Secondary adapters (port implementations)
        llm_adapter = LlmInterpreterAdapter(
            llm_client=self._llm_client,
            config=self._config.llm,
        )
        rules_adapter = RulesAdapter(
            config=self._config.mapping,
        )

        # Application services
        section_selector = FaultSectionSelector(
            rules=rules_adapter,
            llm=llm_adapter,
        )

        mode_router = FaultModeRouter(
            rules=rules_adapter,
            llm=llm_adapter,
        )

        header_builder = FaultHeaderBuilder(
            rules=rules_adapter,
        )

        table_classifier = FaultTableClassifier(
            rules=rules_adapter,
            llm=llm_adapter,
        )

        schematic_correlator = FaultSchematicCorrelator(
            llm=llm_adapter,
            rules=rules_adapter,
        )

        reporting_mapper = FaultReportingMapper(
            llm=llm_adapter,
            rules=rules_adapter,
            table_classifier=table_classifier,
            schematic_correlator=schematic_correlator,
        )

        isolation_mapper = FaultIsolationMapper(
            llm=llm_adapter,
            rules=rules_adapter,
        )

        assembler = FaultModuleAssembler(
            rules=rules_adapter,
            review_policy=self._review_policy,
        )

        # Validation layer
        validator = FaultModuleValidator(
            structural_validator=validate_against_schema,
            business_validator=validate_business_rules,
            review_gate=default_review_gate,
        )

        # Top-level use case
        use_case = FaultMappingUseCase(
            section_selector=section_selector,
            mode_router=mode_router,
            header_builder=header_builder,
            reporting_mapper=reporting_mapper,
            isolation_mapper=isolation_mapper,
            assembler=assembler,
            validator=validator,
        )

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.instrumented_services import (
                InstrumentedFaultMappingUseCase,
            )
            return InstrumentedFaultMappingUseCase(
                inner=use_case, metrics=self._metrics_sink,
            )

        return use_case

    def create_persistence_service(self) -> FaultModulePersistenceService:
        """Wire and return a persistence service.

        If no ``repository`` was injected at construction, a default
        ``InMemoryFaultModuleRepository`` is used.  For MongoDB,
        inject a ``MongoDBFaultModuleRepository`` via the constructor
        or use ``build_mongo_repository()`` to create one from config.

        Returns
        -------
        FaultModulePersistenceService
            Ready to call ``persist(module)``.
        """
        repo = self._repository or InMemoryFaultModuleRepository()
        svc = FaultModulePersistenceService(repository=repo)

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.instrumented_services import (
                InstrumentedFaultModulePersistenceService,
            )
            return InstrumentedFaultModulePersistenceService(
                inner=svc, metrics=self._metrics_sink,
            )

        return svc

    def create_review_service(self) -> FaultModuleReviewService:
        """Wire and return a review workflow service.

        Uses the same repository as the persistence service.  If
        no ``repository`` was injected at construction, a default
        ``InMemoryFaultModuleRepository`` is used.

        An optional ``TrustedModuleHandoffPort`` is wired if one
        was provided at construction time.

        An optional ``AuditRepositoryPort`` is wired if one was
        provided at construction time.

        Returns
        -------
        FaultModuleReviewService
            Ready to call ``approve(record_id)`` or
            ``reject(record_id)``.
        """
        repo = self._repository or InMemoryFaultModuleRepository()
        svc = FaultModuleReviewService(
            repository=repo,
            handoff=self._handoff,
            audit_repo=self._audit_repo,
        )

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.instrumented_services import (
                InstrumentedFaultModuleReviewService,
            )
            return InstrumentedFaultModuleReviewService(
                inner=svc, metrics=self._metrics_sink,
            )

        return svc

    def create_reconciliation_service(
        self,
    ) -> FaultModuleReconciliationService:
        """Wire and return a reconciliation / sweep service.

        Uses the same repository as persistence and review services.
        If no ``repository`` was injected at construction, a default
        ``InMemoryFaultModuleRepository`` is used.

        An optional ``AuditRepositoryPort`` is wired if one was
        provided at construction time.

        Returns
        -------
        FaultModuleReconciliationService
            Ready to call ``sweep()``.
        """
        repo = self._repository or InMemoryFaultModuleRepository()
        svc = FaultModuleReconciliationService(
            repository=repo,
            audit_repo=self._audit_repo,
        )

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.instrumented_services import (
                InstrumentedFaultModuleReconciliationService,
            )
            return InstrumentedFaultModuleReconciliationService(
                inner=svc, metrics=self._metrics_sink,
            )

        return svc

    # ── Async service factories ────────────────────────────────────

    def create_batch_processing_service(self):  # noqa: ANN201
        """Wire and return a sync batch processing service.

        Requires an LLM client (calls ``create_use_case()`` internally).

        Returns
        -------
        FaultBatchProcessingService (or instrumented wrapper)
        """
        from fault_mapper.application.fault_batch_processing_service import (
            FaultBatchProcessingService,
        )

        use_case = self.create_use_case()
        persistence = self.create_persistence_service()
        svc = FaultBatchProcessingService(
            use_case=use_case, persistence=persistence,
        )

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.instrumented_services import (
                InstrumentedFaultBatchProcessingService,
            )
            return InstrumentedFaultBatchProcessingService(
                inner=svc, metrics=self._metrics_sink,
            )

        return svc

    def create_async_batch_processing_service(
        self,
        max_concurrency: int = 5,
    ):  # noqa: ANN201
        """Wire and return an async batch processing service.

        Requires an LLM client (calls ``create_use_case()`` internally).
        The mapping use case is sync; async persistence is used.

        Parameters
        ----------
        max_concurrency : int
            Maximum concurrent items.  Default 5.

        Returns
        -------
        AsyncFaultBatchProcessingService (or instrumented wrapper)
        """
        from fault_mapper.application.async_fault_batch_processing_service import (
            AsyncFaultBatchProcessingService,
        )

        use_case = self.create_use_case()
        persistence = self.create_async_persistence_service()
        svc = AsyncFaultBatchProcessingService(
            use_case=use_case,
            persistence=persistence,
            max_concurrency=max_concurrency,
        )

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.async_instrumented_services import (
                AsyncInstrumentedFaultBatchProcessingService,
            )
            return AsyncInstrumentedFaultBatchProcessingService(
                inner=svc, metrics=self._metrics_sink,
            )

        return svc

    def create_async_persistence_service(self):  # noqa: ANN201
        """Wire and return an async persistence service.

        If no ``async_repository`` was injected at construction, a default
        ``AsyncInMemoryFaultModuleRepository`` is used.
        """
        from fault_mapper.adapters.secondary.async_in_memory_repository import (
            AsyncInMemoryFaultModuleRepository,
        )
        from fault_mapper.application.async_persistence_service import (
            AsyncFaultModulePersistenceService,
        )

        repo = self._async_repository or AsyncInMemoryFaultModuleRepository()
        svc = AsyncFaultModulePersistenceService(repository=repo)

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.async_instrumented_services import (
                AsyncInstrumentedFaultModulePersistenceService,
            )
            return AsyncInstrumentedFaultModulePersistenceService(
                inner=svc, metrics=self._metrics_sink,
            )

        return svc

    def create_async_review_service(self):  # noqa: ANN201
        """Wire and return an async review service."""
        from fault_mapper.adapters.secondary.async_in_memory_repository import (
            AsyncInMemoryFaultModuleRepository,
        )
        from fault_mapper.application.async_review_service import (
            AsyncFaultModuleReviewService,
        )

        repo = self._async_repository or AsyncInMemoryFaultModuleRepository()
        svc = AsyncFaultModuleReviewService(
            repository=repo,
            audit_repo=self._async_audit_repo,
        )

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.async_instrumented_services import (
                AsyncInstrumentedFaultModuleReviewService,
            )
            return AsyncInstrumentedFaultModuleReviewService(
                inner=svc, metrics=self._metrics_sink,
            )

        return svc

    def create_async_reconciliation_service(self):  # noqa: ANN201
        """Wire and return an async reconciliation service."""
        from fault_mapper.adapters.secondary.async_in_memory_repository import (
            AsyncInMemoryFaultModuleRepository,
        )
        from fault_mapper.application.async_reconciliation_service import (
            AsyncFaultModuleReconciliationService,
        )

        repo = self._async_repository or AsyncInMemoryFaultModuleRepository()
        svc = AsyncFaultModuleReconciliationService(
            repository=repo,
            audit_repo=self._async_audit_repo,
        )

        if self._metrics_sink is not None:
            from fault_mapper.adapters.secondary.async_instrumented_services import (
                AsyncInstrumentedFaultModuleReconciliationService,
            )
            return AsyncInstrumentedFaultModuleReconciliationService(
                inner=svc, metrics=self._metrics_sink,
            )

        return svc

    def build_mongo_repository(self) -> Any:
        """Build a ``MongoDBFaultModuleRepository`` from the current config.

        Requires ``pymongo`` to be installed.

        Returns
        -------
        MongoDBFaultModuleRepository
            Ready to pass to ``create_persistence_service()`` or
            directly to the ``FaultMapperFactory`` constructor.
        """
        from fault_mapper.adapters.secondary.mongodb_repository import (
            MongoDBFaultModuleRepository,
        )
        return MongoDBFaultModuleRepository(config=self._config.mongo)


def build_fault_mapper(
    config: AppConfig | None = None,
    llm_client: Any = None,
    review_policy: MappingReviewPolicyPort | None = None,
    repository: FaultModuleRepositoryPort | None = None,
    handoff: TrustedModuleHandoffPort | None = None,
    audit_repo: AuditRepositoryPort | None = None,
    metrics_sink: MetricsSinkPort | None = None,
) -> FaultMappingUseCase:
    """One-call factory function -- the simplest way to get a wired use case.

    Parameters
    ----------
    config : AppConfig | None
        Application configuration.  Uses defaults if None.
    llm_client : Any
        A callable conforming to the OpenAI chat-completions shape.
    review_policy : MappingReviewPolicyPort | None
        Optional review-policy implementation.
    repository : FaultModuleRepositoryPort | None
        Optional persistence repository (passed through to factory).
    handoff : TrustedModuleHandoffPort | None
        Optional downstream handoff hook.
    audit_repo : AuditRepositoryPort | None
        Optional audit repository for review event logging.
    metrics_sink : MetricsSinkPort | None
        Optional metrics sink for instrumentation.

    Returns
    -------
    FaultMappingUseCase
        Ready to call execute(source).
    """
    if config is None:
        config = AppConfig()
    factory = FaultMapperFactory(
        config=config,
        llm_client=llm_client,
        review_policy=review_policy,
        repository=repository,
        handoff=handoff,
        audit_repo=audit_repo,
        metrics_sink=metrics_sink,
    )
    return factory.create_use_case()
