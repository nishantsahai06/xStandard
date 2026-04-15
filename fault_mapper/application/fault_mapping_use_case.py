"""Primary use case — orchestrate the full mapping pipeline.

This is the **single entry-point** that calling code (REST handler,
CLI, Celery task, …) invokes.  It coordinates all application-layer
services in a deterministic pipeline:

  1. **Select** fault-relevant sections.
  2. **Route** the fault mode (reporting vs isolation).
  3. **Build** the S1000D DM header.
  4. **Map** content via the mode-specific mapper.
  5. **Assemble** the canonical ``S1000DFaultDataModule`` with full
     provenance and traceability.
  6. **Validate** the assembled module (structural + business rules)
     and gate for review.

Responsibility boundaries:
  • Owns the top-level workflow sequence.
  • Does **NOT** contain mapping or classification logic itself.
  • Does **NOT** call LLMs or rules directly — delegates through
    injected services which themselves depend on domain ports.
"""

from __future__ import annotations

from fault_mapper.domain.enums import FaultMode
from fault_mapper.domain.models import (
    DocumentPipelineOutput,
    S1000DFaultDataModule,
)
from fault_mapper.domain.value_objects import FieldOrigin

from fault_mapper.application.fault_section_selector import (
    FaultSectionSelector,
)
from fault_mapper.application.fault_mode_router import FaultModeRouter
from fault_mapper.application.fault_header_builder import FaultHeaderBuilder
from fault_mapper.application.fault_reporting_mapper import (
    FaultReportingMapper,
)
from fault_mapper.application.fault_isolation_mapper import (
    FaultIsolationMapper,
)
from fault_mapper.application.fault_module_assembler import (
    FaultModuleAssembler,
)
from fault_mapper.application.fault_module_validator import (
    FaultModuleValidator,
)


class FaultMappingUseCase:
    """Orchestrates the complete fault-module mapping pipeline.

    All collaborators are constructor-injected.  The use case itself
    has **no direct dependency on domain ports** — it depends only on
    application-layer services (which in turn depend on ports).

    Typical construction happens in the infrastructure factory.
    """

    def __init__(
        self,
        section_selector: FaultSectionSelector,
        mode_router: FaultModeRouter,
        header_builder: FaultHeaderBuilder,
        reporting_mapper: FaultReportingMapper,
        isolation_mapper: FaultIsolationMapper,
        assembler: FaultModuleAssembler,
        validator: FaultModuleValidator | None = None,
    ) -> None:
        self._section_selector = section_selector
        self._mode_router = mode_router
        self._header_builder = header_builder
        self._reporting_mapper = reporting_mapper
        self._isolation_mapper = isolation_mapper
        self._assembler = assembler
        self._validator = validator

    # ── Public API ───────────────────────────────────────────────

    def execute(
        self,
        source: DocumentPipelineOutput,
    ) -> S1000DFaultDataModule:
        """Run the full mapping pipeline.

        Parameters
        ----------
        source
            Normalised output from the document-extraction pipeline.

        Returns
        -------
        S1000DFaultDataModule
            The fully assembled canonical fault data module with
            provenance, mapping trace, and staged-trust metadata.

        Raises
        ------
        ValueError
            If no fault-relevant sections are found in ``source``.
        """
        # ── Step 1: select fault-relevant sections ───────────────
        sections, selection_origins = self._section_selector.select(source)

        if not sections:
            raise ValueError(
                f"No fault-relevant sections found in document "
                f"'{source.file_name}' (id={source.id})"
            )

        # ── Step 2: determine fault mode ─────────────────────────
        mode, mode_origin = self._mode_router.resolve(sections)

        # ── Step 3: build S1000D DM header ───────────────────────
        header, header_origins = self._header_builder.build(source, mode)

        # ── Step 4: map content (mode-specific) ──────────────────
        fault_reporting = None
        fault_isolation = None
        content_origins: dict[str, FieldOrigin] = {}

        if mode is FaultMode.FAULT_REPORTING:
            fault_reporting, content_origins = (
                self._reporting_mapper.map(
                    sections, content_origins, source.schematics,
                )
            )
        else:
            fault_isolation, content_origins = (
                self._isolation_mapper.map(sections, content_origins)
            )

        # ── Step 5: assemble root aggregate ──────────────────────
        module = self._assembler.assemble(
            source=source,
            mode=mode,
            header=header,
            fault_reporting=fault_reporting,
            fault_isolation=fault_isolation,
            selected_sections=sections,
            header_origins=header_origins,
            content_origins=content_origins,
            selection_origins=selection_origins,
            mode_origin=mode_origin,
        )

        # ── Step 6: validate and gate for review ─────────────────
        if self._validator is not None:
            self._validator.validate(module)

        return module
