"""Procedural reference extractor — cross-references, figures, tables.

Three-pass strategy:
  1. **RULE/DIRECT** — deterministic regex for known reference patterns
     and direct cataloging of image/table assets.
  2. **LLM** — semantic extraction of ambiguous cross-references.
  3. **Dedup** — merge and deduplicate by target ID.
"""

from __future__ import annotations

import re

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.models import FigureRef, Section
from fault_mapper.domain.procedural_models import (
    ProceduralReference,
    ProceduralTableRef,
)
from fault_mapper.domain.procedural_ports import (
    ProceduralLlmInterpreterPort,
    ProceduralRulesEnginePort,
)
from fault_mapper.domain.value_objects import FieldOrigin

from fault_mapper.application._shared_helpers import section_key


# ── Deterministic patterns ───────────────────────────────────────────

_FIGURE_PATTERN = re.compile(
    r"(?:see\s+|refer\s+to\s+)?(?:figure|fig\.?)\s+(\d+[\w.-]*)",
    re.IGNORECASE,
)
_TABLE_PATTERN = re.compile(
    r"(?:see\s+|refer\s+to\s+)?(?:table|tbl\.?)\s+(\d+[\w.-]*)",
    re.IGNORECASE,
)
_DM_REF_PATTERN = re.compile(
    r"(?:see\s+|refer\s+to\s+)?(?:DMC|DM)\s*[-:]?\s*([\w-]+)",
    re.IGNORECASE,
)


class ProceduralReferenceExtractor:
    """Extracts references, figures and table refs from source sections.

    Constructor-injected dependencies:
      ``rules`` — confidence thresholds.
      ``llm``   — semantic fallback for ambiguous cross-references.
    """

    def __init__(
        self,
        rules: ProceduralRulesEnginePort,
        llm: ProceduralLlmInterpreterPort,
    ) -> None:
        self._rules = rules
        self._llm = llm

    # ── Public API ───────────────────────────────────────────────

    def extract(
        self,
        sections: list[Section],
        existing_origins: dict[str, FieldOrigin],
    ) -> tuple[
        list[ProceduralReference],
        list[FigureRef],
        list[ProceduralTableRef],
        dict[str, FieldOrigin],
    ]:
        """Extract all reference types from source sections.

        Returns
        -------
        tuple
            (procedural_refs, figure_refs, table_refs, origins)
        """
        threshold = self._rules.llm_confidence_threshold(
            "reference_extraction",
        )

        all_refs: list[ProceduralReference] = []
        all_figures: list[FigureRef] = []
        all_tables: list[ProceduralTableRef] = []
        origins: dict[str, FieldOrigin] = {}

        for section in sections:
            sec_key = section_key(section)

            # Pass 1: deterministic regex extraction
            det_refs, det_origins = self._extract_by_regex(
                section, sec_key,
            )
            all_refs.extend(det_refs)
            origins.update(det_origins)

            # Pass 2: catalog assets
            figs, fig_origins = self._catalog_figures(section, sec_key)
            all_figures.extend(figs)
            origins.update(fig_origins)

            tbls, tbl_origins = self._catalog_tables(section, sec_key)
            all_tables.extend(tbls)
            origins.update(tbl_origins)

            # Pass 3: LLM for ambiguous references
            llm_refs, llm_origins = self._extract_by_llm(
                section, sec_key, threshold,
            )
            all_refs.extend(llm_refs)
            origins.update(llm_origins)

        # Deduplicate
        all_refs = _deduplicate_refs(all_refs)
        all_figures = _deduplicate_figures(all_figures)

        return all_refs, all_figures, all_tables, origins

    # ── Internals ────────────────────────────────────────────────

    def _extract_by_regex(
        self,
        section: Section,
        sec_key: str,
    ) -> tuple[list[ProceduralReference], dict[str, FieldOrigin]]:
        """Deterministic regex extraction of references."""
        refs: list[ProceduralReference] = []
        origins: dict[str, FieldOrigin] = {}
        text = section.section_text
        src_path = f"sections[{section.section_order}].section_text"

        for match in _DM_REF_PATTERN.finditer(text):
            refs.append(ProceduralReference(
                ref_type="dm_ref",
                target_dm_code=match.group(1),
                label=match.group(0).strip(),
            ))
            origins[f"ref.regex.{sec_key}.dm_{match.start()}"] = FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path=src_path,
                confidence=1.0,
                source_chunk_id=section.id,
            )

        for match in _FIGURE_PATTERN.finditer(text):
            refs.append(ProceduralReference(
                ref_type="figure_ref",
                target_id=f"fig-{match.group(1)}",
                label=match.group(0).strip(),
            ))
            origins[f"ref.regex.{sec_key}.fig_{match.start()}"] = FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path=src_path,
                confidence=1.0,
                source_chunk_id=section.id,
            )

        for match in _TABLE_PATTERN.finditer(text):
            refs.append(ProceduralReference(
                ref_type="table_ref",
                target_id=f"tbl-{match.group(1)}",
                label=match.group(0).strip(),
            ))
            origins[f"ref.regex.{sec_key}.tbl_{match.start()}"] = FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path=src_path,
                confidence=1.0,
                source_chunk_id=section.id,
            )

        return refs, origins

    def _catalog_figures(
        self,
        section: Section,
        sec_key: str,
    ) -> tuple[list[FigureRef], dict[str, FieldOrigin]]:
        """Build FigureRef per image asset."""
        figs: list[FigureRef] = []
        origins: dict[str, FieldOrigin] = {}

        for idx, image in enumerate(section.images):
            figs.append(FigureRef(
                figure_id=image.id or f"fig-{sec_key}-{idx}",
                caption=image.caption,
            ))
            origins[f"fig.{sec_key}.{idx}"] = FieldOrigin(
                strategy=MappingStrategy.DIRECT,
                source_path=(
                    f"sections[{section.section_order}].images[{idx}]"
                ),
                confidence=1.0,
                source_chunk_id=image.id,
            )

        return figs, origins

    def _catalog_tables(
        self,
        section: Section,
        sec_key: str,
    ) -> tuple[list[ProceduralTableRef], dict[str, FieldOrigin]]:
        """Build ProceduralTableRef per table asset."""
        tables: list[ProceduralTableRef] = []
        origins: dict[str, FieldOrigin] = {}

        for idx, table in enumerate(section.tables):
            tables.append(ProceduralTableRef(
                table_id=f"tbl-{sec_key}-{idx}",
                caption=table.caption,
                source_table_id=table.id,
            ))
            origins[f"tbl.{sec_key}.{idx}"] = FieldOrigin(
                strategy=MappingStrategy.DIRECT,
                source_path=(
                    f"sections[{section.section_order}].tables[{idx}]"
                ),
                confidence=1.0,
                source_chunk_id=table.id,
            )

        return tables, origins

    def _extract_by_llm(
        self,
        section: Section,
        sec_key: str,
        threshold: float,
    ) -> tuple[list[ProceduralReference], dict[str, FieldOrigin]]:
        """LLM-based extraction for ambiguous references."""
        refs: list[ProceduralReference] = []
        origins: dict[str, FieldOrigin] = {}

        interpretations = self._llm.interpret_references(
            section.section_text,
        )

        for idx, interp in enumerate(interpretations):
            if interp.confidence < threshold:
                continue

            refs.append(ProceduralReference(
                ref_type=interp.ref_type,
                target_dm_code=interp.target_dm_code,
                target_id=interp.target_id,
                label=interp.label or interp.target_text,
            ))
            origins[f"ref.llm.{sec_key}.{idx}"] = FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path=(
                    f"sections[{section.section_order}].section_text"
                ),
                confidence=interp.confidence,
                source_chunk_id=section.id,
            )

        return refs, origins


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _deduplicate_refs(
    refs: list[ProceduralReference],
) -> list[ProceduralReference]:
    """Deduplicate by (ref_type, target_dm_code, target_id)."""
    seen: set[tuple[str, str | None, str | None]] = set()
    unique: list[ProceduralReference] = []
    for ref in refs:
        key = (ref.ref_type, ref.target_dm_code, ref.target_id)
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return unique


def _deduplicate_figures(figs: list[FigureRef]) -> list[FigureRef]:
    """Deduplicate by figure_id."""
    seen: set[str | None] = set()
    unique: list[FigureRef] = []
    for fig in figs:
        if fig.figure_id not in seen:
            seen.add(fig.figure_id)
            unique.append(fig)
    return unique
