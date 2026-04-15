"""Procedural-specific frozen value objects.

Shared VOs (DmCode, Language, IssueInfo, IssueDate, DmTitle,
FieldOrigin, MappingTrace, ValidationIssue, ModuleValidationResult,
ReviewDecision) live in ``fault_mapper.domain.value_objects``.

This file defines ONLY the VOs that have no fault-pipeline equivalent:

  A. LLM interpretation results — consumed by procedural application
     services, never written directly into canonical output.
  B. Procedural lineage — per-section mapping trace supplement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fault_mapper.domain.procedural_enums import (
    ActionType,
    ProceduralSectionType,
)


# ═══════════════════════════════════════════════════════════════════════
#  A.  LLM INTERPRETATION RESULTS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SectionClassificationResult:
    """LLM classification of a source section's procedural role."""

    section_type: ProceduralSectionType
    confidence: float
    reasoning: str


@dataclass(frozen=True)
class StepInterpretation:
    """LLM-extracted procedural step from unstructured text.

    Schema-aligned fields: stepNumber, text, actionType, expectedResult.
    ``sub_step_hints`` carries child numbering strings (e.g. ["3.a",
    "3.b"]) so the step extractor can wire nesting.
    """

    step_number: str
    text: str
    action_type: ActionType = ActionType.GENERAL
    expected_result: str | None = None
    has_warning: bool = False
    has_caution: bool = False
    has_note: bool = False
    sub_step_hints: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True)
class RequirementInterpretation:
    """LLM-extracted preliminary requirement from unstructured text."""

    requirement_type: str   # "personnel"|"equipment"|"supply"|"spare"|"safety"
    name: str | None = None
    quantity: float = 0.0
    unit: str | None = None
    role: str | None = None
    skill_level: str | None = None
    ident_number: str | None = None
    safety_text: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class ReferenceInterpretation:
    """LLM-extracted cross-reference from procedural text."""

    ref_type: str   # "dm_ref" | "figure_ref" | "table_ref" | "external"
    target_text: str
    target_dm_code: str | None = None
    target_id: str | None = None
    label: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class ProceduralRelevanceAssessment:
    """LLM assessment of whether a section contains procedural content.

    Analogous to ``FaultRelevanceAssessment`` in the fault pipeline.
    """

    is_relevant: bool
    confidence: float
    reasoning: str


# ═══════════════════════════════════════════════════════════════════════
#  B.  PROCEDURAL LINEAGE (per-section trace supplement)
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProceduralSectionLineage:
    """Per-section trace within a procedural mapping run.

    Used to populate per-section entries in the top-level lineage
    block of the canonical schema.
    """

    source_section_ids: list[str] = field(default_factory=list)
    source_chunk_ids: list[str] = field(default_factory=list)
    step_count: int = 0
    confidence: float = 0.0
