"""Fault-relevant section selector.

Analyses the sections of a ``DocumentPipelineOutput`` and returns only
those that contain fault-related content.

Strategy (two-pass):
  1. **RULE** — deterministic keyword matching against section titles /
     text, and section-type allow-listing.
  2. **LLM**  — semantic relevance assessment as a fallback for
     sections that passed neither keyword nor type checks.

The selector never mutates source or target models.
"""

from __future__ import annotations

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.models import DocumentPipelineOutput, Section
from fault_mapper.domain.ports import LlmInterpreterPort, RulesEnginePort
from fault_mapper.domain.value_objects import FieldOrigin
from fault_mapper.application._shared_helpers import section_key

from fault_mapper.application._shared_helpers import section_key


class FaultSectionSelector:
    """Selects fault-relevant sections from pipeline output.

    Constructor-injected dependencies:
      ``rules`` — keyword sets, section-type sets, thresholds.
      ``llm``   — semantic fallback for ambiguous sections.
    """

    def __init__(
        self,
        rules: RulesEnginePort,
        llm: LlmInterpreterPort,
    ) -> None:
        self._rules = rules
        self._llm = llm

    # ── Public API ───────────────────────────────────────────────

    def select(
        self,
        source: DocumentPipelineOutput,
    ) -> tuple[list[Section], dict[str, FieldOrigin]]:
        """Return fault-relevant sections and per-section provenance.

        Returns
        -------
        tuple[list[Section], dict[str, FieldOrigin]]
            * Sections selected as fault-relevant (in original order).
            * A mapping of ``section_key → FieldOrigin`` explaining
              **why** each section was included.
        """
        # RULE: load deterministic configuration once
        keywords = self._rules.fault_relevance_keywords()
        section_types = self._rules.fault_relevant_section_types()
        threshold = self._rules.llm_confidence_threshold("fault_relevance")

        selected: list[Section] = []
        origins: dict[str, FieldOrigin] = {}

        for section in source.sections:
            key = section_key(section)
            origin = self._evaluate(section, keywords, section_types, threshold)
            if origin is not None:
                selected.append(section)
                origins[key] = origin

        return selected, origins

    # ── Internals ────────────────────────────────────────────────

    def _evaluate(
        self,
        section: Section,
        keywords: frozenset[str],
        section_types: frozenset[str],
        threshold: float,
    ) -> FieldOrigin | None:
        """Evaluate one section.  Returns ``FieldOrigin`` if relevant,
        ``None`` otherwise."""

        # ── RULE pass 1: section type allow-list ─────────────────
        if section.section_type.lower() in section_types:
            return FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path=f"sections[{section.section_order}].section_type",
                confidence=1.0,
                source_chunk_id=section.id,
            )

        # ── RULE pass 2: keyword match in title + text ───────────
        haystack = f"{section.section_title} {section.section_text}".lower()
        if any(kw in haystack for kw in keywords):
            return FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path=f"sections[{section.section_order}].section_title",
                confidence=1.0,
                source_chunk_id=section.id,
            )

        # ── LLM fallback: semantic assessment ────────────────────
        assessment = self._llm.assess_fault_relevance(section)
        if assessment.is_relevant and assessment.confidence >= threshold:
            return FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path=f"sections[{section.section_order}]",
                confidence=assessment.confidence,
                source_chunk_id=section.id,
            )

        return None



