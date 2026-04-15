"""Fault mode router — determines faultReporting vs faultIsolation.

Strategy (two-pass):
  1. **RULE** — deterministic structural signals (section types,
     keyword density, section-title patterns).
  2. **LLM**  — semantic interpretation if the rule pass returns
     ``None`` (inconclusive).

The final decision is always deterministic: the LLM result is only
accepted when its confidence meets or exceeds the configured threshold.
If neither pass is conclusive, the router defaults to
``FaultMode.FAULT_REPORTING`` and records a low-confidence origin.
"""

from __future__ import annotations

from fault_mapper.domain.enums import FaultMode, MappingStrategy
from fault_mapper.domain.models import Section
from fault_mapper.domain.ports import LlmInterpreterPort, RulesEnginePort
from fault_mapper.domain.value_objects import FieldOrigin


class FaultModeRouter:
    """Resolves the fault mode for a batch of selected sections.

    Constructor-injected dependencies:
      ``rules`` — structural heuristic.
      ``llm``   — semantic fallback.
    """

    def __init__(
        self,
        rules: RulesEnginePort,
        llm: LlmInterpreterPort,
    ) -> None:
        self._rules = rules
        self._llm = llm

    def resolve(
        self,
        sections: list[Section],
    ) -> tuple[FaultMode, FieldOrigin]:
        """Determine the fault mode and return its provenance.

        Returns
        -------
        tuple[FaultMode, FieldOrigin]
            The resolved mode and the origin explaining how it was
            derived.

        Raises
        ------
        ValueError
            If ``sections`` is empty.
        """
        if not sections:
            raise ValueError("Cannot resolve mode from an empty section list")

        # ── RULE: deterministic structural assessment ────────────
        rule_mode = self._rules.assess_mode_by_structure(sections)
        if rule_mode is not None:
            return rule_mode, FieldOrigin(
                strategy=MappingStrategy.RULE,
                source_path="sections[*].section_type",
                confidence=1.0,
            )

        # ── LLM fallback ────────────────────────────────────────
        threshold = self._rules.llm_confidence_threshold("fault_mode")
        interpretation = self._llm.interpret_fault_mode(sections)

        if interpretation.confidence >= threshold:
            return interpretation.mode, FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path="sections[*]",
                confidence=interpretation.confidence,
            )

        # ── Below threshold — conservative default ───────────────
        # Default to FAULT_REPORTING and propagate the actual
        # (low) confidence so the assembler can flag it for review.
        return FaultMode.FAULT_REPORTING, FieldOrigin(
            strategy=MappingStrategy.LLM,
            source_path="sections[*]",
            confidence=interpretation.confidence,
        )
