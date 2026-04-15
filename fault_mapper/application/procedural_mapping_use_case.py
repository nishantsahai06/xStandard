"""Primary use case — orchestrate the full procedural mapping pipeline.

This is the **single entry-point** that calling code (REST handler,
CLI, Celery task, …) invokes.  It coordinates all application-layer
services in a deterministic pipeline:

  1. **Classify** — select procedural-relevant sections.
  2. **Build header** — deterministic DM header construction.
  3. **Organize** — classify and order sections into shells.
  4. **Extract steps** — build populated sections (NO MUTATION).
  5. **Extract requirements** — preliminary requirements.
  6. **Extract references** — cross-refs, figures, tables.
  7. **Assemble** — compose the root aggregate with provenance.

Critical design constraint (Chunk 1 risk fix):
  Section shells from the organizer are NEVER mutated in-place.
  Step extraction produces NEW ``ProceduralSection`` objects via
  ``dataclasses.replace()`` — copy-on-write semantics.

Mirrors ``FaultMappingUseCase`` structurally, but with procedural-
specific stages replacing fault-specific stages (no mode router,
no isolation/reporting fork).
"""

from __future__ import annotations

from dataclasses import replace

from fault_mapper.domain.models import DocumentPipelineOutput, Section
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import (
    ProceduralSection,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.value_objects import FieldOrigin

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


class ProceduralMappingUseCase:
    """Orchestrates the complete procedural-module mapping pipeline.

    All collaborators are constructor-injected.  The use case itself
    has **no direct dependency on domain ports** — it depends only on
    application-layer services (which in turn depend on ports).

    Typical construction happens in ``ProceduralMapperFactory``.
    """

    def __init__(
        self,
        classifier: ProceduralDocumentClassifier,
        organizer: ProceduralSectionOrganizer,
        header_builder: ProceduralHeaderBuilder,
        step_extractor: ProceduralStepExtractor,
        requirement_extractor: ProceduralRequirementExtractor,
        reference_extractor: ProceduralReferenceExtractor,
        assembler: ProceduralModuleAssembler,
    ) -> None:
        self._classifier = classifier
        self._organizer = organizer
        self._header_builder = header_builder
        self._step_extractor = step_extractor
        self._requirement_extractor = requirement_extractor
        self._reference_extractor = reference_extractor
        self._assembler = assembler

    # ── Public API ───────────────────────────────────────────────

    def execute(
        self,
        source: DocumentPipelineOutput,
        module_type: ProceduralModuleType = ProceduralModuleType.PROCEDURAL,
    ) -> S1000DProceduralDataModule:
        """Run the full procedural mapping pipeline.

        Parameters
        ----------
        source
            Normalised output from the document-extraction pipeline.
        module_type
            Whether this is PROCEDURAL or DESCRIPTIVE (defaults PROCEDURAL).

        Returns
        -------
        S1000DProceduralDataModule
            Fully assembled procedural data module with provenance,
            mapping trace, and staged-trust metadata.

        Raises
        ------
        ValueError
            If no procedural-relevant sections are found in ``source``.
        """
        # ── Step 1: classify procedural-relevant sections ────────
        sections, class_origins = self._classifier.classify(source)

        if not sections:
            raise ValueError(
                f"No procedural-relevant sections found in document "
                f"'{source.file_name}' (id={source.id})"
            )

        # ── Step 2: build S1000D DM header ───────────────────────
        header, header_origins = self._header_builder.build(
            source, module_type,
        )

        # ── Step 3: organize sections into shells (no steps) ─────
        shells, org_origins = self._organizer.organize(sections)

        # ── Step 4: extract steps, build NEW sections ────────────
        #    Uses dataclasses.replace() — NO in-place mutation.
        all_origins: dict[str, FieldOrigin] = {}
        all_origins.update(class_origins)
        all_origins.update(header_origins)
        all_origins.update(org_origins)

        populated_sections = self._populate_sections(
            shells, sections, all_origins,
        )

        # ── Step 5: extract preliminary requirements ─────────────
        req_items, req_origins = self._requirement_extractor.extract(
            sections, all_origins,
        )
        all_origins.update(req_origins)

        # ── Step 6: extract references ───────────────────────────
        refs, figure_refs, table_refs, ref_origins = (
            self._reference_extractor.extract(sections, all_origins)
        )
        all_origins.update(ref_origins)

        # ── Step 7: assemble root aggregate ──────────────────────
        module = self._assembler.assemble(
            source=source,
            module_type=module_type,
            header=header,
            sections=populated_sections,
            requirements=req_items,
            refs=refs,
            figure_refs=figure_refs,
            table_refs=table_refs,
            all_origins=all_origins,
            selected_sections=sections,
        )

        return module

    # ── Internals ────────────────────────────────────────────────

    def _populate_sections(
        self,
        shells: list[ProceduralSection],
        source_sections: list[Section],
        all_origins: dict[str, FieldOrigin],
    ) -> list[ProceduralSection]:
        """Build new ProceduralSection objects with steps populated.

        Uses ``dataclasses.replace()`` to produce new section objects
        rather than mutating shells in-place.

        The mapping from procedural shell → source section is via
        ``shell.source_section_id``.
        """
        source_map: dict[str, Section] = {
            _section_key(s): s for s in source_sections
        }

        populated: list[ProceduralSection] = []

        for shell in shells:
            src = source_map.get(shell.source_section_id or "")
            if src is None:
                # No matching source section — keep shell as-is
                populated.append(shell)
                continue

            steps, step_origins = self._step_extractor.extract(
                src, all_origins,
            )
            all_origins.update(step_origins)

            # Build NEW section with steps — no mutation of shell
            new_section = replace(shell, steps=steps)
            populated.append(new_section)

        return populated


# ── Module-level helpers ─────────────────────────────────────────────


def _section_key(section: Section) -> str:
    """Stable key for a section (prefers ``id``, falls back to order)."""
    return section.id or f"section_{section.section_order}"
