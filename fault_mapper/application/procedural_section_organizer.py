"""Procedural section organizer — classifies and orders sections.

Two-pass strategy (mirrors the classification stage of the fault pipeline):
  1. **RULE** — deterministic section-type classification by structure.
  2. **LLM**  — semantic classification fallback.

Returns ProceduralSection shells (steps are NOT populated here —
that is the step extractor's job).  The use case is responsible for
populating steps into new section objects without mutation.
"""

from __future__ import annotations

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.models import Section
from fault_mapper.domain.procedural_enums import ProceduralSectionType
from fault_mapper.domain.procedural_models import ProceduralSection
from fault_mapper.domain.procedural_ports import (
    ProceduralLlmInterpreterPort,
    ProceduralRulesEnginePort,
)
from fault_mapper.domain.value_objects import FieldOrigin

from fault_mapper.application._shared_helpers import section_key


class ProceduralSectionOrganizer:
    """Classifies, orders, and groups source sections into shells.

    Constructor-injected dependencies:
      ``rules`` — structural classification heuristics.
      ``llm``   — semantic classification fallback.
    """

    def __init__(
        self,
        rules: ProceduralRulesEnginePort,
        llm: ProceduralLlmInterpreterPort,
    ) -> None:
        self._rules = rules
        self._llm = llm

    # ── Public API ───────────────────────────────────────────────

    def organize(
        self,
        sections: list[Section],
    ) -> tuple[list[ProceduralSection], dict[str, FieldOrigin]]:
        """Classify sections and return ProceduralSection shells.

        Steps are NOT populated here — that is the step extractor's
        job.  This service only creates the section skeleton with
        ``section_type``, ``section_id``, ``title``, ordering, and
        level.

        Returns
        -------
        tuple[list[ProceduralSection], dict[str, FieldOrigin]]
            Shells in schema-correct order and per-classification
            origins.
        """
        threshold = self._rules.llm_confidence_threshold(
            "section_classification",
        )

        shells: list[ProceduralSection] = []
        origins: dict[str, FieldOrigin] = {}

        for section in sections:
            section_type, origin = self._classify(section, threshold)
            key = f"section_type.{section_key(section)}"
            origins[key] = origin

            shell = ProceduralSection(
                section_id=section.id or f"sec_{section.section_order}",
                title=section.section_title,
                section_order=section.section_order,
                section_type=section_type,
                level=section.level,
                page_numbers=list(section.page_numbers),
                raw_section_text=section.section_text,
                source_section_id=section_key(section),
            )
            shells.append(shell)

        # Sort by section_order to ensure schema ordering
        shells.sort(key=lambda s: s.section_order)

        return shells, origins

    # ── Internals ────────────────────────────────────────────────

    def _classify(
        self,
        section: Section,
        threshold: float,
    ) -> tuple[ProceduralSectionType, FieldOrigin]:
        """Classify one section.  Returns type and origin."""

        # ── RULE: try deterministic classification ───────────────
        rule_type = self._rules.classify_section_by_structure(section)
        if rule_type is not None:
            return rule_type, FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path=(
                    f"sections[{section.section_order}].section_type"
                ),
                confidence=1.0,
                source_chunk_id=section.id,
            )

        # ── LLM fallback ────────────────────────────────────────
        result = self._llm.classify_section(section)
        if result.confidence >= threshold:
            return result.section_type, FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path=f"sections[{section.section_order}]",
                confidence=result.confidence,
                source_chunk_id=section.id,
            )

        # ── Default: GENERAL if neither pass is confident ────────
        return ProceduralSectionType.GENERAL, FieldOrigin(
            strategy=MappingStrategy.RULE,
            source_path=(
                f"sections[{section.section_order}].default"
            ),
            confidence=0.5,
            source_chunk_id=section.id,
        )

