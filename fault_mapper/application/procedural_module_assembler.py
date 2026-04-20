"""Procedural module assembler — deterministic final assembly.

The **ONLY** place where the canonical ``S1000DProceduralDataModule``
root aggregate is constructed.  Takes all pre-computed pieces produced
by upstream services and wires them into the final object with full
traceability.

Critical invariants (mirrors ``FaultModuleAssembler``):
  • **No LLM calls.**
  • **No external I/O.**
  • **Purely deterministic** — same inputs always produce same output.
  • Every field origin is recorded in the ``MappingTrace``.
  • **No validation logic** — assembly only, validation is a separate
    concern.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fault_mapper.domain.enums import (
    ClassificationMethod,
    MappingStrategy,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    Classification,
    DocumentPipelineOutput,
    FigureRef,
    Provenance,
    Section,
)
from fault_mapper.domain.ports import MappingReviewPolicyPort
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import (
    ProceduralContent,
    ProceduralHeader,
    ProceduralLineage,
    ProceduralReference,
    ProceduralRequirementItem,
    ProceduralSection,
    ProceduralTableRef,
    ProceduralValidationResults,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.procedural_ports import ProceduralRulesEnginePort
from fault_mapper.domain.procedural_value_objects import (
    ProceduralConfidence,
    SourceSectionRef,
)
from fault_mapper.domain.value_objects import FieldOrigin, MappingTrace


_MAPPING_VERSION = "1.0.0"


class ProceduralModuleAssembler:
    """Assembles all sub-results into a single S1000DProceduralDataModule.

    Reuses the shared ``MappingReviewPolicyPort`` for review-status
    decisions — no procedural-specific review port required.

    Constructor-injected dependencies:
      ``rules``         — record-ID generation.
      ``review_policy`` — optional review-policy boundary hook.
    """

    def __init__(
        self,
        rules: ProceduralRulesEnginePort,
        review_policy: MappingReviewPolicyPort | None = None,
    ) -> None:
        self._rules = rules
        self._review_policy = review_policy

    # ── Public API ───────────────────────────────────────────────

    def assemble(
        self,
        *,
        source: DocumentPipelineOutput,
        module_type: ProceduralModuleType,
        header: ProceduralHeader,
        sections: list[ProceduralSection],
        requirements: list[ProceduralRequirementItem],
        refs: list[ProceduralReference],
        figure_refs: list[FigureRef],
        table_refs: list[ProceduralTableRef],
        all_origins: dict[str, FieldOrigin],
        selected_sections: list[Section],
    ) -> S1000DProceduralDataModule:
        """Compose and return the root aggregate.

        Assembly pipeline:
          1. Generate record ID via rules.
          2. Build ProceduralContent from sections + requirements.
          3. Build Provenance (source lineage).
          4. Build MappingTrace from all_origins.
          5. Build ProceduralLineage (schema-aligned).
          6. Build Classification metadata.
          7. Determine initial review status via policy.
          8. Compose root aggregate.

        Parameters
        ----------
        source
            Original pipeline output (for provenance).
        module_type
            PROCEDURAL or DESCRIPTIVE.
        header
            Pre-built DM header.
        sections
            Populated ProceduralSection objects (with steps).
        requirements
            Extracted requirement items.
        refs / figure_refs / table_refs
            Extracted reference objects.
        all_origins
            Per-field provenance from all upstream services.
        selected_sections
            Original source sections (for provenance building).

        Returns
        -------
        S1000DProceduralDataModule
        """
        # 1. Record ID
        record_id = self._rules.generate_record_id()

        # 2. Content
        content = ProceduralContent(
            preliminary_requirements=requirements,
            sections=sections,
        )

        # 3. Provenance (WHERE did data come from?)
        provenance = _build_provenance(source, selected_sections)

        # 4. Mapping trace (HOW was each field produced?)
        trace = _build_trace(all_origins)

        # 5. Lineage (schema-aligned mapping metadata)
        lineage = _build_lineage(selected_sections, trace)

        # 6. Classification
        classification = _build_classification(trace)

        # 7. Review status
        review_status = self._determine_review_status(trace)

        return S1000DProceduralDataModule(
            record_id=record_id,
            module_type=module_type,
            source=provenance,
            ident_and_status_section=header,
            content=content,
            validation=ProceduralValidationResults(
                status=ValidationStatus.PENDING,
            ),
            lineage=lineage,
            mapping_version=_MAPPING_VERSION,
            review_status=review_status,
            classification=classification,
            trace=trace,
        )

    # ── Internals ────────────────────────────────────────────────

    def _determine_review_status(
        self,
        trace: MappingTrace,
    ) -> ReviewStatus:
        """RULE: delegate to policy port or default to NOT_REVIEWED."""
        if self._review_policy is not None:
            return self._review_policy.determine_initial_review_status(
                trace,
            )
        return ReviewStatus.NOT_REVIEWED


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL HELPERS  (pure, no port access)
# ═══════════════════════════════════════════════════════════════════════


def _build_provenance(
    source: DocumentPipelineOutput,
    sections: list[Section],
) -> Provenance:
    """RULE: gather source-lineage references."""
    section_ids: list[str] = []
    pages: list[int] = []
    chunk_ids: list[str] = []
    table_ids: list[str] = []
    image_ids: list[str] = []

    for section in sections:
        if section.id:
            section_ids.append(section.id)
        pages.extend(section.page_numbers)
        for chunk in section.chunks:
            if chunk.id:
                chunk_ids.append(chunk.id)
        for table in section.tables:
            if table.id:
                table_ids.append(table.id)
        for image in section.images:
            if image.id:
                image_ids.append(image.id)

    return Provenance(
        source_document_id=source.id,
        source_section_ids=section_ids,
        source_pages=sorted(set(pages)),
        source_chunk_ids=chunk_ids,
        source_table_ids=table_ids,
        source_image_ids=image_ids,
        file_name=source.file_name,
        file_type=source.file_type,
        source_path=source.source_path,
    )


def _build_trace(
    all_origins: dict[str, FieldOrigin],
) -> MappingTrace:
    """RULE: merge per-phase field origins into one ``MappingTrace``."""
    warnings: list[str] = []

    llm_count = sum(
        1 for v in all_origins.values()
        if v.strategy == MappingStrategy.LLM
    )
    low_conf = [
        k for k, v in all_origins.items() if v.confidence < 0.7
    ]

    if llm_count:
        warnings.append(f"{llm_count} field(s) derived via LLM")
    if low_conf:
        warnings.append(
            f"{len(low_conf)} field(s) below 0.7 confidence: "
            f"{', '.join(low_conf[:5])}"
        )

    return MappingTrace(
        field_origins=dict(all_origins),
        warnings=warnings,
        mapped_at=datetime.now(timezone.utc).isoformat(),
    )


def _build_lineage(
    sections: list[Section],
    trace: MappingTrace,
) -> ProceduralLineage:
    """Build schema-aligned lineage block with structured confidence."""
    origins = trace.field_origins
    avg_conf = (
        sum(o.confidence for o in origins.values()) / len(origins)
        if origins
        else 0.0
    )
    avg_conf = round(avg_conf, 3)

    llm_count = sum(
        1 for o in origins.values()
        if o.strategy == MappingStrategy.LLM
    )
    if llm_count == 0:
        method = "rules"
    elif llm_count == len(origins):
        method = "llm"
    else:
        method = "llm+rules"

    # Structured source section refs (with page numbers)
    source_section_refs = [
        SourceSectionRef(
            section_id=s.id,
            page_numbers=tuple(s.page_numbers),
        )
        for s in sections
        if s.id
    ]

    # Multi-dimensional confidence — use avg as default for each
    # dimension.  Future chunks can feed per-dimension values.
    confidence = ProceduralConfidence(
        document_classification=avg_conf,
        dm_code_inference=avg_conf,
        section_typing=avg_conf,
        step_segmentation=avg_conf,
    )

    return ProceduralLineage(
        mapped_by="fault_mapper.procedural",
        mapped_at=trace.mapped_at or datetime.now(timezone.utc).isoformat(),
        mapping_ruleset_version=_MAPPING_VERSION,
        mapping_method=method,
        source_sections=source_section_refs,
        confidence=confidence,
    )


def _build_classification(trace: MappingTrace) -> Classification:
    """RULE: compute aggregate confidence and dominant method."""
    origins = trace.field_origins
    if not origins:
        return Classification(confidence=0.0)

    total_conf = sum(o.confidence for o in origins.values())
    avg_conf = total_conf / len(origins)

    llm_count = sum(
        1 for o in origins.values()
        if o.strategy == MappingStrategy.LLM
    )
    if llm_count == 0:
        method = ClassificationMethod.RULES
    elif llm_count == len(origins):
        method = ClassificationMethod.LLM
    else:
        method = ClassificationMethod.LLM_RULES

    return Classification(
        domain="S1000D",
        confidence=round(avg_conf, 3),
        method=method,
    )
