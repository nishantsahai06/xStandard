"""Fake LLM interpreter — in-memory test double for ``LlmInterpreterPort``.

All 7 methods are implemented.  Each returns canned defaults that can be
overridden via constructor arguments or by mutating the public attributes
after construction.

Supports call tracking: every method appends its arguments to a public
``calls`` dict keyed by method name so tests can assert invocation count
and argument values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fault_mapper.domain.enums import FaultMode, TableType
from fault_mapper.domain.models import SchematicsItem, Section, TableAsset
from fault_mapper.domain.value_objects import (
    FaultDescriptionInterpretation,
    FaultModeInterpretation,
    FaultRelevanceAssessment,
    IsolationStepInterpretation,
    LruSruExtraction,
    SchematicCorrelation,
    TableClassification,
)


class FakeLlmInterpreter:
    """Configurable fake implementing ``LlmInterpreterPort``.

    Every public attribute below is the canned return value for the
    corresponding method.  Override per-test as needed.
    """

    def __init__(self) -> None:
        # ── Canned return values (override per test) ─────────────
        self.relevance_result = FaultRelevanceAssessment(
            is_relevant=True,
            confidence=0.95,
            reasoning="Fake: section is fault-relevant.",
        )
        self.mode_result = FaultModeInterpretation(
            mode=FaultMode.FAULT_REPORTING,
            confidence=0.90,
            reasoning="Fake: interpreted as fault-reporting.",
        )
        self.description_results: list[FaultDescriptionInterpretation] = [
            FaultDescriptionInterpretation(
                description="Fake fault description",
                system_name="Hydraulic System",
                fault_code_suggestion="FC-001",
                fault_equipment="Pump Assembly",
                fault_message="Overpressure detected",
                confidence=0.92,
            ),
        ]
        self.isolation_step_results: list[IsolationStepInterpretation] = [
            IsolationStepInterpretation(
                step_number=1,
                instruction="Check hydraulic pressure gauge.",
                question="Is pressure within limits?",
                yes_next=2,
                no_next=3,
                confidence=0.90,
            ),
            IsolationStepInterpretation(
                step_number=2,
                instruction="System is normal.",
                confidence=0.90,
            ),
            IsolationStepInterpretation(
                step_number=3,
                instruction="Replace hydraulic pump.",
                confidence=0.90,
            ),
        ]
        self.table_classification_result = TableClassification(
            role=TableType.LRU_LIST,
            confidence=0.88,
            reasoning="Fake: table looks like an LRU list.",
        )
        self.lru_sru_results: list[LruSruExtraction] = [
            LruSruExtraction(
                name="Hydraulic Pump",
                short_name="HYD-PUMP",
                ident_number="29-10-01",
                is_lru=True,
                confidence=0.91,
            ),
        ]
        self.correlation_result = SchematicCorrelation(
            matched_descriptions=["Fake fault description"],
            matched_components=["Resistor R1"],
            confidence=0.85,
            reasoning="Fake: schematic correlates with fault.",
        )

        # ── Call tracker ─────────────────────────────────────────
        self.calls: dict[str, list[Any]] = {
            "assess_fault_relevance": [],
            "interpret_fault_mode": [],
            "interpret_fault_descriptions": [],
            "interpret_isolation_steps": [],
            "classify_table": [],
            "extract_lru_sru": [],
            "correlate_schematic": [],
        }

    # ── LlmInterpreterPort methods ──────────────────────────────

    def assess_fault_relevance(
        self,
        section: Section,
    ) -> FaultRelevanceAssessment:
        self.calls["assess_fault_relevance"].append(section)
        return self.relevance_result

    def interpret_fault_mode(
        self,
        sections: list[Section],
    ) -> FaultModeInterpretation:
        self.calls["interpret_fault_mode"].append(sections)
        return self.mode_result

    def interpret_fault_descriptions(
        self,
        text: str,
        context: str,
    ) -> list[FaultDescriptionInterpretation]:
        self.calls["interpret_fault_descriptions"].append((text, context))
        return list(self.description_results)

    def interpret_isolation_steps(
        self,
        text: str,
        context: str,
    ) -> list[IsolationStepInterpretation]:
        self.calls["interpret_isolation_steps"].append((text, context))
        return list(self.isolation_step_results)

    def classify_table(
        self,
        table: TableAsset,
    ) -> TableClassification:
        self.calls["classify_table"].append(table)
        return self.table_classification_result

    def extract_lru_sru(
        self,
        text: str,
    ) -> list[LruSruExtraction]:
        self.calls["extract_lru_sru"].append(text)
        return list(self.lru_sru_results)

    def correlate_schematic(
        self,
        schematic: SchematicsItem,
        fault_descriptions: list[str],
    ) -> SchematicCorrelation:
        self.calls["correlate_schematic"].append(
            (schematic, fault_descriptions),
        )
        return self.correlation_result
