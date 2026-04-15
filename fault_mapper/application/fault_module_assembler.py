"""Fault module assembler — deterministic final assembly.

This is the **ONLY** place where the canonical
``S1000DFaultDataModule`` root aggregate is constructed.  It takes all
pre-computed pieces produced by upstream services and wires them into
the final object with full traceability.

Critical invariants:
  • **No LLM calls.**
  • **No external I/O.**
  • **Purely deterministic** — same inputs always produce same output.
  • Every field origin is recorded in the ``MappingTrace``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fault_mapper.domain.enums import (
    ClassificationMethod,
    FaultMode,
    MappingStrategy,
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    Classification,
    DocumentPipelineOutput,
    FaultContent,
    FaultHeader,
    FaultIsolationContent,
    FaultReportingContent,
    Provenance,
    S1000DFaultDataModule,
    Section,
    ValidationResults,
)
from fault_mapper.domain.ports import (
    MappingReviewPolicyPort,
    RulesEnginePort,
)
from fault_mapper.domain.value_objects import FieldOrigin, MappingTrace


_MAPPING_VERSION = "1.0.0"


class FaultModuleAssembler:
    """Assembles the final canonical ``S1000DFaultDataModule``.

    All field values arrive pre-computed.  The assembler's job is to:
      1. Wire everything into the root aggregate.
      2. Merge per-field provenance into a single ``MappingTrace``.
      3. Build ``Provenance`` (source lineage).
      4. Determine initial ``ReviewStatus`` via the optional review
         policy port (defaults to ``NOT_REVIEWED`` if absent).
      5. Set initial ``ValidationStatus`` to ``PENDING``.

    Constructor-injected dependencies:
      ``rules``         — record-ID generation.
      ``review_policy`` — optional review-policy boundary hook.
    """

    def __init__(
        self,
        rules: RulesEnginePort,
        review_policy: MappingReviewPolicyPort | None = None,
    ) -> None:
        self._rules = rules
        self._review_policy = review_policy

    # ── Public API ───────────────────────────────────────────────

    def assemble(
        self,
        source: DocumentPipelineOutput,
        mode: FaultMode,
        header: FaultHeader,
        fault_reporting: FaultReportingContent | None,
        fault_isolation: FaultIsolationContent | None,
        selected_sections: list[Section],
        header_origins: dict[str, FieldOrigin],
        content_origins: dict[str, FieldOrigin],
        selection_origins: dict[str, FieldOrigin],
        mode_origin: FieldOrigin,
    ) -> S1000DFaultDataModule:
        """Assemble and return the complete fault data module.

        Parameters
        ----------
        source
            Original pipeline output (for provenance).
        mode
            Resolved content mode.
        header
            Pre-built DM header.
        fault_reporting / fault_isolation
            Mode-specific content block (exactly one is non-``None``).
        selected_sections
            Sections used during mapping (for provenance).
        header_origins / content_origins / selection_origins
            Per-field provenance from each upstream service.
        mode_origin
            Provenance for the mode decision.

        Returns
        -------
        S1000DFaultDataModule
        """
        # ── RULE: generate record ID ─────────────────────────────
        record_id = self._rules.generate_record_id()

        # ── RULE: wrap content ───────────────────────────────────
        content = FaultContent(
            fault_reporting=fault_reporting,
            fault_isolation=fault_isolation,
        )

        # ── RULE: provenance (WHERE did data come from?) ─────────
        provenance = _build_provenance(source, selected_sections)

        # ── RULE: mapping trace (HOW was each field produced?) ───
        trace = _build_trace(
            header_origins,
            content_origins,
            selection_origins,
            mode_origin,
        )

        # ── RULE: review status ──────────────────────────────────
        review_status = self._determine_review_status(trace)

        # ── RULE: classification metadata ────────────────────────
        classification = _build_classification(trace)

        return S1000DFaultDataModule(
            record_id=record_id,
            mode=mode,
            header=header,
            content=content,
            provenance=provenance,
            mapping_version=_MAPPING_VERSION,
            validation_status=ValidationStatus.PENDING,
            review_status=review_status,
            validation_results=ValidationResults(),
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
    schematic_refs: list[str] = []

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

    for schematic in source.schematics:
        ref = schematic.id or schematic.source_path
        if ref:
            schematic_refs.append(ref)

    return Provenance(
        source_document_id=source.id,
        source_section_ids=section_ids,
        source_pages=sorted(set(pages)),
        source_chunk_ids=chunk_ids,
        source_table_ids=table_ids,
        source_image_ids=image_ids,
        source_schematic_refs=schematic_refs,
    )


def _build_trace(
    header_origins: dict[str, FieldOrigin],
    content_origins: dict[str, FieldOrigin],
    selection_origins: dict[str, FieldOrigin],
    mode_origin: FieldOrigin,
) -> MappingTrace:
    """RULE: merge per-phase field origins into one ``MappingTrace``."""
    merged: dict[str, FieldOrigin] = {}
    merged.update(selection_origins)
    merged["mode"] = mode_origin
    merged.update(header_origins)
    merged.update(content_origins)

    # Derive warnings from the trace
    warnings: list[str] = []
    llm_count = sum(
        1 for v in merged.values()
        if v.strategy == MappingStrategy.LLM
    )
    low_conf = [
        k for k, v in merged.items() if v.confidence < 0.7
    ]

    if llm_count:
        warnings.append(f"{llm_count} field(s) derived via LLM")
    if low_conf:
        warnings.append(
            f"{len(low_conf)} field(s) below 0.7 confidence: "
            f"{', '.join(low_conf[:5])}"
        )

    return MappingTrace(
        field_origins=merged,
        warnings=warnings,
        mapped_at=datetime.now(timezone.utc).isoformat(),
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
