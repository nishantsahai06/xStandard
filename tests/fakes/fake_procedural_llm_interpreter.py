"""Fake procedural LLM interpreter — in-memory test double for ``ProceduralLlmInterpreterPort``.

All 6 methods are implemented.  Each returns canned defaults that can be
overridden via constructor arguments or by mutating the public attributes
after construction.

Supports call tracking: every method appends its arguments to a public
``calls`` dict keyed by method name so tests can assert invocation count
and argument values.
"""

from __future__ import annotations

from typing import Any

from fault_mapper.domain.models import Section, TableAsset
from fault_mapper.domain.procedural_enums import (
    ActionType,
    ProceduralSectionType,
)
from fault_mapper.domain.procedural_value_objects import (
    ProceduralRelevanceAssessment,
    ReferenceInterpretation,
    RequirementInterpretation,
    SectionClassificationResult,
    StepInterpretation,
)


class FakeProceduralLlmInterpreter:
    """Configurable fake implementing ``ProceduralLlmInterpreterPort``.

    Every public attribute below is the canned return value for the
    corresponding method.  Override per-test as needed.
    """

    def __init__(self) -> None:
        # ── Canned return values (override per test) ─────────────
        self.relevance_result = ProceduralRelevanceAssessment(
            is_relevant=True,
            confidence=0.95,
            reasoning="Fake: section is procedural-relevant.",
        )
        self.classification_result = SectionClassificationResult(
            section_type=ProceduralSectionType.PROCEDURE,
            confidence=0.90,
            reasoning="Fake: classified as procedure.",
        )
        self.step_results: list[StepInterpretation] = [
            StepInterpretation(
                step_number="1",
                text="Remove the access panel.",
                action_type=ActionType.REMOVE,
                expected_result="Panel removed",
                confidence=0.92,
            ),
            StepInterpretation(
                step_number="2",
                text="Inspect the hydraulic line.",
                action_type=ActionType.INSPECT,
                expected_result="No leaks observed",
                confidence=0.90,
            ),
        ]
        self.requirement_results: list[RequirementInterpretation] = [
            RequirementInterpretation(
                requirement_type="equipment",
                name="Torque Wrench",
                ident_number="TW-100",
                quantity=1.0,
                confidence=0.88,
            ),
        ]
        self.reference_results: list[ReferenceInterpretation] = [
            ReferenceInterpretation(
                ref_type="dm_ref",
                target_text="See DMC-TEST-001",
                target_dm_code="DMC-TEST-001",
                confidence=0.85,
            ),
        ]
        self.table_classification_result = SectionClassificationResult(
            section_type=ProceduralSectionType.SETUP,
            confidence=0.87,
            reasoning="Fake: table classified as setup.",
        )

        # ── Call tracker ─────────────────────────────────────────
        self.calls: dict[str, list[Any]] = {
            "assess_procedural_relevance": [],
            "classify_section": [],
            "interpret_procedural_steps": [],
            "interpret_requirements": [],
            "interpret_references": [],
            "classify_procedural_table": [],
        }

    # ── ProceduralLlmInterpreterPort methods ─────────────────────

    def assess_procedural_relevance(
        self,
        section: Section,
    ) -> ProceduralRelevanceAssessment:
        self.calls["assess_procedural_relevance"].append(section)
        return self.relevance_result

    def classify_section(
        self,
        section: Section,
    ) -> SectionClassificationResult:
        self.calls["classify_section"].append(section)
        return self.classification_result

    def interpret_procedural_steps(
        self,
        text: str,
        context: str,
    ) -> list[StepInterpretation]:
        self.calls["interpret_procedural_steps"].append((text, context))
        return list(self.step_results)

    def interpret_requirements(
        self,
        text: str,
        context: str,
    ) -> list[RequirementInterpretation]:
        self.calls["interpret_requirements"].append((text, context))
        return list(self.requirement_results)

    def interpret_references(
        self,
        text: str,
    ) -> list[ReferenceInterpretation]:
        self.calls["interpret_references"].append(text)
        return list(self.reference_results)

    def classify_procedural_table(
        self,
        table: TableAsset,
    ) -> SectionClassificationResult:
        self.calls["classify_procedural_table"].append(table)
        return self.table_classification_result
