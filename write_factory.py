"""Helper script to write factory.py - run once then delete."""
import pathlib

CONTENT = '''\
"""Dependency-injection factory -- wires the full object graph.

This is the COMPOSITION ROOT of the application.  It is the only module
that knows about concrete adapter classes.  Everything else depends only
on domain ports (protocols).

Two entry points:
1. FaultMapperFactory(config).create_use_case()  -- OOP style
2. build_fault_mapper(config, llm_client)         -- functional shortcut

Both return a fully wired FaultMappingUseCase ready for
use_case.execute(source).

LLM client injection:
The caller (CLI, web handler, test harness) is responsible for
constructing the LLM client and passing it in.  This factory does NOT
read API keys or create HTTP clients -- that is the caller concern.

If llm_client is None the factory raises ValueError at create_use_case
time (fail-fast, not fail-silent).
"""

from __future__ import annotations

from typing import Any

from fault_mapper.infrastructure.config import AppConfig, MappingConfig

# Adapter imports (infrastructure is the ONLY layer that may do this)
from fault_mapper.adapters.secondary.llm_interpreter_adapter import (
    LlmInterpreterAdapter,
)
from fault_mapper.adapters.secondary.rules_adapter import RulesAdapter

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

# Domain port for optional review policy
from fault_mapper.domain.ports import MappingReviewPolicyPort


class FaultMapperFactory:
    """Composition root -- builds the fully wired use case.

    Accepts an AppConfig and an LLM client callable, and produces
    a ready-to-use FaultMappingUseCase with all dependencies injected.
    """

    def __init__(
        self,
        config: AppConfig,
        llm_client: Any = None,
        review_policy: MappingReviewPolicyPort | None = None,
    ) -> None:
        self._config = config
        self._llm_client = llm_client
        self._review_policy = review_policy

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

        # Top-level use case
        return FaultMappingUseCase(
            section_selector=section_selector,
            mode_router=mode_router,
            header_builder=header_builder,
            reporting_mapper=reporting_mapper,
            isolation_mapper=isolation_mapper,
            assembler=assembler,
        )


def build_fault_mapper(
    config: AppConfig | None = None,
    llm_client: Any = None,
    review_policy: MappingReviewPolicyPort | None = None,
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
    )
    return factory.create_use_case()
'''

target = pathlib.Path("fault_mapper/infrastructure/factory.py")
target.write_text(CONTENT)
print(f"OK: wrote {len(CONTENT)} bytes to {target}")
