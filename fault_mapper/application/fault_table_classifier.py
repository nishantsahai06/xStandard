"""Fault table classifier — determines the role of each extracted table.

Strategy (two-pass):
  1. **RULE** — normalise column headers via the rules engine, then
     pattern-match against known header signatures.
  2. **LLM**  — semantic classification when header patterns are
     ambiguous or the table has no headers at all.

Tables may represent LRU lists, SRU lists, spare-part requirements,
support-equipment requirements, supply requirements, fault-code
look-ups, or general/unknown data.
"""

from __future__ import annotations

from fault_mapper.domain.enums import TableType
from fault_mapper.domain.models import TableAsset
from fault_mapper.domain.ports import LlmInterpreterPort, RulesEnginePort
from fault_mapper.domain.value_objects import TableClassification


class FaultTableClassifier:
    """Classifies tables by their role inside the fault data module.

    Constructor-injected dependencies:
      ``rules`` — header normalisation, header-pattern matching,
                  confidence threshold.
      ``llm``   — semantic classification fallback.
    """

    def __init__(
        self,
        rules: RulesEnginePort,
        llm: LlmInterpreterPort,
    ) -> None:
        self._rules = rules
        self._llm = llm

    # ── Public API ───────────────────────────────────────────────

    def classify(self, table: TableAsset) -> TableClassification:
        """Classify a single table and return the typed result.

        Returns
        -------
        TableClassification
            ``role`` (``TableType``), ``confidence``, ``reasoning``.
        """
        # ── RULE: header pattern matching ────────────────────────
        if table.headers:
            normalized = self._rules.normalize_table_headers(table.headers)
            rule_role = self._rules.classify_table_by_headers(normalized)
            if rule_role is not None:
                return TableClassification(
                    role=rule_role,
                    confidence=1.0,
                    reasoning=(
                        f"Rule-based: normalised headers matched "
                        f"pattern for {rule_role.value}"
                    ),
                )

        # ── LLM fallback ────────────────────────────────────────
        threshold = self._rules.llm_confidence_threshold(
            "table_classification",
        )
        llm_result = self._llm.classify_table(table)

        if llm_result.confidence >= threshold:
            return llm_result

        # Below threshold — mark as UNKNOWN with actual confidence
        return TableClassification(
            role=TableType.UNKNOWN,
            confidence=llm_result.confidence,
            reasoning=(
                f"Below threshold ({threshold:.2f}): "
                f"{llm_result.reasoning}"
            ),
        )

    def classify_all(
        self,
        tables: list[TableAsset],
    ) -> dict[str, TableClassification]:
        """Classify every table in the list, keyed by table ID or index.

        Returns
        -------
        dict[str, TableClassification]
            A mapping of ``table_key → classification``.
        """
        results: dict[str, TableClassification] = {}
        for idx, table in enumerate(tables):
            key = table.id or f"table_{idx}"
            results[key] = self.classify(table)
        return results
