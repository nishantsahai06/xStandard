"""Fault schematic correlator — links schematics to fault entries.

Cross-references schematic diagrams extracted by the pipeline with
fault descriptions produced by the reporting mapper.

Strategy:
  1. **RULE** — component-name overlap with fault-description text.
  2. **RULE** — page-number proximity to fault-relevant sections.
  3. **LLM**  — semantic correlation as a fallback, gated by the
     configured confidence threshold (consistent two-pass pattern).
"""

from __future__ import annotations

from fault_mapper.domain.models import FigureRef, SchematicsItem
from fault_mapper.domain.ports import LlmInterpreterPort, RulesEnginePort


class FaultSchematicCorrelator:
    """Correlates schematics with fault descriptions and sections.

    Constructor-injected dependencies:
      ``llm``   — semantic correlation fallback.
      ``rules`` — confidence threshold lookup.
    """

    def __init__(
        self,
        llm: LlmInterpreterPort,
        rules: RulesEnginePort,
    ) -> None:
        self._llm = llm
        self._rules = rules

    # ── Public API ───────────────────────────────────────────────

    def correlate(
        self,
        schematics: list[SchematicsItem],
        fault_descriptions: list[str],
        relevant_pages: list[int],
    ) -> list[FigureRef]:
        """Return figure references that link schematics to faults.

        Parameters
        ----------
        schematics
            Schematic diagrams extracted by the pipeline.
        fault_descriptions
            Plain-text fault descriptions already built by the
            reporting mapper.
        relevant_pages
            Page numbers of fault-relevant sections (for proximity
            matching).

        Returns
        -------
        list[FigureRef]
            Figure references to attach to the content block.
        """
        refs: list[FigureRef] = []

        for schematic in schematics:
            # ── RULE: deterministic matching first ───────────────
            ref = self._try_deterministic(
                schematic, fault_descriptions, relevant_pages,
            )
            if ref is not None:
                refs.append(ref)
                continue

            # ── LLM fallback (threshold-gated) ──────────────────
            ref = self._try_llm(schematic, fault_descriptions)
            if ref is not None:
                refs.append(ref)

        return refs

    # ── Internals ────────────────────────────────────────────────

    def _try_deterministic(
        self,
        schematic: SchematicsItem,
        fault_descriptions: list[str],
        relevant_pages: list[int],
    ) -> FigureRef | None:
        """RULE: match by component-name overlap or page proximity."""

        component_names = {
            c.name.lower()
            for c in schematic.components
            if c.name
        }

        # ── RULE: component name appears in a fault description ──
        if component_names:
            for desc in fault_descriptions:
                desc_lower = desc.lower()
                if any(name in desc_lower for name in component_names):
                    return _figure_ref_from(schematic)

        # ── RULE: schematic page falls within fault-relevant pages
        if schematic.page_number and schematic.page_number in relevant_pages:
            return _figure_ref_from(schematic)

        return None

    def _try_llm(
        self,
        schematic: SchematicsItem,
        fault_descriptions: list[str],
    ) -> FigureRef | None:
        """LLM fallback: semantic correlation, gated by threshold."""
        if not fault_descriptions:
            return None

        # LLM: ask for correlation assessment
        correlation = self._llm.correlate_schematic(
            schematic, fault_descriptions,
        )

        # RULE: threshold gate — consistent with all other services
        threshold = self._rules.llm_confidence_threshold("schematic")
        if (
            correlation.matched_descriptions
            and correlation.confidence >= threshold
        ):
            return _figure_ref_from(schematic)

        return None


# ── Module-level helpers ─────────────────────────────────────────────


def _figure_ref_from(schematic: SchematicsItem) -> FigureRef:
    """Build a ``FigureRef`` from a ``SchematicsItem``."""
    return FigureRef(
        figure_id=schematic.id or schematic.source_path,
        caption=f"Schematic (page {schematic.page_number})",
    )
