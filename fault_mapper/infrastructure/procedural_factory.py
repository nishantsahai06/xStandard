"""Procedural dependency-injection factory — composition root.

Mirrors ``FaultMapperFactory`` structurally.  Wires the complete
procedural object graph and returns a ready-to-use
``ProceduralMappingUseCase`` and ``ProceduralModuleValidator``.

This is the ONLY module that knows about concrete adapter classes.
Everything else depends only on domain ports (protocols).

LLM client injection:
The caller (CLI, web handler, test harness) is responsible for
constructing the LLM client and passing it in.  This factory does NOT
read API keys or create HTTP clients.
"""

from __future__ import annotations

from typing import Any

from fault_mapper.infrastructure.procedural_config import (
    ProceduralAppConfig,
)

# ── Shared ports (REUSED, not procedural-specific) ──
from fault_mapper.domain.ports import (
    FaultModuleRepositoryPort,
    MappingReviewPolicyPort,
)

# ── Application-layer imports ────────────────────────────────────
from fault_mapper.application.procedural_mapping_use_case import (
    ProceduralMappingUseCase,
)
from fault_mapper.application.procedural_document_classifier import (
    ProceduralDocumentClassifier,
)
from fault_mapper.application.procedural_section_organizer import (
    ProceduralSectionOrganizer,
)
from fault_mapper.application.procedural_header_builder import (
    ProceduralHeaderBuilder,
)
from fault_mapper.application.procedural_step_extractor import (
    ProceduralStepExtractor,
)
from fault_mapper.application.procedural_requirement_extractor import (
    ProceduralRequirementExtractor,
)
from fault_mapper.application.procedural_reference_extractor import (
    ProceduralReferenceExtractor,
)
from fault_mapper.application.procedural_module_assembler import (
    ProceduralModuleAssembler,
)
from fault_mapper.application.procedural_module_validator import (
    ProceduralModuleValidator,
)
from fault_mapper.application.procedural_module_persistence_service import (
    ProceduralModulePersistenceService,
)
from fault_mapper.application.procedural_batch_processing_service import (
    ProceduralBatchProcessingService,
)
from fault_mapper.application.async_procedural_batch_processing_service import (
    AsyncProceduralBatchProcessingService,
)
from fault_mapper.application.async_procedural_module_persistence_service import (
    AsyncProceduralModulePersistenceService,
)
from fault_mapper.infrastructure._instrumentation import wrap_with_metrics


class ProceduralMapperFactory:
    """Composition root — builds the fully wired procedural use case.

    Accepts a ``ProceduralAppConfig`` and an LLM client callable,
    and produces a ready-to-use ``ProceduralMappingUseCase``.

    Pattern mirrors ``FaultMapperFactory`` exactly:
    1. Caller constructs factory with config + LLM client.
    2. ``create_use_case()`` wires the full object graph.
    3. Returned use case is the single entry-point.
    """

    def __init__(
        self,
        config: ProceduralAppConfig,
        llm_client: Any = None,
        repository: FaultModuleRepositoryPort | None = None,
    ) -> None:
        if llm_client is None:
            raise ValueError(
                "ProceduralMapperFactory requires an llm_client.  "
                "Pass the LLM client (OpenAI, Anthropic, or local) "
                "at construction time."
            )
        self._config = config
        self._llm_client = llm_client
        self._repository = repository

    def create_use_case(
        self,
        review_policy: MappingReviewPolicyPort | None = None,
    ) -> ProceduralMappingUseCase:
        """Wire and return a fully configured ProceduralMappingUseCase.

        Parameters
        ----------
        review_policy
            Optional review gate.  Uses the SHARED
            ``MappingReviewPolicyPort`` — not a procedural-specific
            port — because its ``evaluate(MappingTrace) -> ReviewStatus``
            signature is type-compatible.

        Returns
        -------
        ProceduralMappingUseCase
            Ready to call ``use_case.execute(source)``.
        """
        from fault_mapper.adapters.secondary.procedural_llm_interpreter_adapter import (
            ProceduralLlmInterpreterAdapter,
        )
        from fault_mapper.adapters.secondary.procedural_rules_adapter import (
            ProceduralRulesAdapter,
        )

        llm = ProceduralLlmInterpreterAdapter(
            llm_client=self._llm_client,
            config=self._config.llm,
        )
        rules = ProceduralRulesAdapter(config=self._config.mapping)

        classifier = ProceduralDocumentClassifier(rules=rules, llm=llm)
        organizer = ProceduralSectionOrganizer(rules=rules, llm=llm)
        header = ProceduralHeaderBuilder(rules=rules)
        steps = ProceduralStepExtractor(rules=rules, llm=llm)
        reqs = ProceduralRequirementExtractor(rules=rules, llm=llm)
        refs = ProceduralReferenceExtractor(rules=rules, llm=llm)
        assembler = ProceduralModuleAssembler(
            rules=rules,
            review_policy=review_policy,
        )

        return ProceduralMappingUseCase(
            classifier=classifier,
            organizer=organizer,
            header_builder=header,
            step_extractor=steps,
            requirement_extractor=reqs,
            reference_extractor=refs,
            assembler=assembler,
        )

    def create_validator(self) -> ProceduralModuleValidator:
        """Wire and return a fully configured ProceduralModuleValidator.

        Uses the concrete schema validator, business-rule validator,
        and review gate from the adapters layer.

        Returns
        -------
        ProceduralModuleValidator
            Ready to call ``validator.validate(module)``.
        """
        from fault_mapper.adapters.secondary.procedural_schema_validator import (
            validate_procedural_schema,
        )
        from fault_mapper.adapters.secondary.procedural_business_rule_validator import (
            validate_procedural_business_rules,
        )
        from fault_mapper.adapters.secondary.procedural_review_gate import (
            procedural_review_gate,
        )

        return ProceduralModuleValidator(
            structural_validator=validate_procedural_schema,
            business_validator=validate_procedural_business_rules,
            review_gate=procedural_review_gate,
        )

    def create_persistence_service(self) -> ProceduralModulePersistenceService:
        """Wire and return a fully configured ProceduralModulePersistenceService.

        If no repository was provided at factory construction time,
        defaults to ``InMemoryFaultModuleRepository`` (shared adapter).

        Returns
        -------
        ProceduralModulePersistenceService
            Ready to call ``service.persist(module)``.
        """
        repo = self._repository
        if repo is None:
            from fault_mapper.adapters.secondary.in_memory_repository import (
                InMemoryFaultModuleRepository,
            )
            repo = InMemoryFaultModuleRepository()

        return ProceduralModulePersistenceService(repository=repo)

    def create_batch_processing_service(
        self,
        *,
        metrics_sink: object | None = None,
    ) -> ProceduralBatchProcessingService:
        """Create a sync procedural batch processing service.

        If ``metrics_sink`` is provided, wraps with instrumented wrapper.
        """
        use_case = self.create_use_case()
        persistence = self.create_persistence_service()
        inner = ProceduralBatchProcessingService(
            use_case=use_case, persistence=persistence,
        )

        from fault_mapper.adapters.secondary.procedural_instrumented_services import (
            InstrumentedProceduralBatchProcessingService,
        )
        return wrap_with_metrics(inner, metrics_sink, InstrumentedProceduralBatchProcessingService)

    def create_async_persistence_service(
        self,
    ) -> AsyncProceduralModulePersistenceService:
        """Create an async procedural persistence service."""
        if self._repository is not None:
            from fault_mapper.adapters.secondary.async_in_memory_repository import (
                AsyncInMemoryFaultModuleRepository,
            )
            repo: object = AsyncInMemoryFaultModuleRepository()
        else:
            from fault_mapper.adapters.secondary.async_in_memory_repository import (
                AsyncInMemoryFaultModuleRepository,
            )
            repo = AsyncInMemoryFaultModuleRepository()

        return AsyncProceduralModulePersistenceService(repository=repo)

    def create_async_batch_processing_service(
        self,
        *,
        metrics_sink: object | None = None,
        max_concurrency: int = 5,
    ) -> AsyncProceduralBatchProcessingService:
        """Create an async procedural batch processing service.

        If ``metrics_sink`` is provided, wraps with instrumented wrapper.
        """
        use_case = self.create_use_case()
        persistence = self.create_async_persistence_service()
        inner = AsyncProceduralBatchProcessingService(
            use_case=use_case,
            persistence=persistence,
            max_concurrency=max_concurrency,
        )

        from fault_mapper.adapters.secondary.procedural_instrumented_services import (
            AsyncInstrumentedProceduralBatchProcessingService,
        )
        return wrap_with_metrics(inner, metrics_sink, AsyncInstrumentedProceduralBatchProcessingService)
