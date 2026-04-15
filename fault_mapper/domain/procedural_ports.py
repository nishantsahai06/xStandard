"""Procedural-specific domain ports.

WHY THIS FILE EXISTS (proof that shared ports are insufficient)
──────────────────────────────────────────────────────────────
``LlmInterpreterPort`` (ports.py) — ALL 7 methods are fault-specific:
  • assess_fault_relevance → FaultRelevanceAssessment
  • interpret_fault_mode → FaultModeInterpretation
  • interpret_fault_descriptions → list[FaultDescriptionInterpretation]
  • interpret_isolation_steps → list[IsolationStepInterpretation]
  • classify_table → TableClassification (fault TableType)
  • extract_lru_sru → list[LruSruExtraction]
  • correlate_schematic → SchematicCorrelation

None of these methods return procedural VOs or accept procedural
parameters.  The procedural pipeline needs step extraction, section
classification, requirement extraction, and reference extraction —
entirely different operations with different return types.

``RulesEnginePort`` (ports.py) — 6 of 14 methods are fault-specific:
  • fault_relevance_keywords, fault_relevant_section_types
  • assess_mode_by_structure (returns FaultMode)
  • classify_table_by_headers (returns fault TableType)
  • derive_fault_code
  • build_dm_code (takes FaultMode param)

The 8 shared-looking methods (generate_record_id, resolve_issue_info,
resolve_issue_date, default_language, llm_confidence_threshold,
normalize_table_headers, normalize_title, determine_info_code)
can't be extracted without modifying the existing port — and 3 of them
(build_dm_code, normalize_title, determine_info_code) take FaultMode
as a parameter, so they need different signatures for procedural use.

SHARED PORTS THAT ARE REUSED (no duplication):
  • FaultModuleRepositoryPort — generic persistence
  • AuditRepositoryPort — generic audit events
  • MetricsSinkPort — generic metrics
  • TrustedModuleHandoffPort — generic handoff
  • MappingReviewPolicyPort — generic review policy (takes MappingTrace)
  • All async variants
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fault_mapper.domain.models import (
    DocumentPipelineOutput,
    Section,
    TableAsset,
)
from fault_mapper.domain.procedural_enums import (
    ProceduralModuleType,
    ProceduralSectionType,
)
from fault_mapper.domain.procedural_value_objects import (
    ProceduralRelevanceAssessment,
    ReferenceInterpretation,
    RequirementInterpretation,
    SectionClassificationResult,
    StepInterpretation,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    IssueDate,
    IssueInfo,
    Language,
)


# ═══════════════════════════════════════════════════════════════════════
#  1. PROCEDURAL LLM INTERPRETER PORT
#
#  6 methods — none overlap with LlmInterpreterPort's 7.
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class ProceduralLlmInterpreterPort(Protocol):
    """LLM semantic interpretation for procedural content.

    Same contract rules as ``LlmInterpreterPort``:
      • Returns typed interpretation VOs, never canonical models.
      • Stateless between calls.
      • Implementations populate ``confidence`` and ``reasoning``.
    """

    def assess_procedural_relevance(
        self,
        section: Section,
    ) -> ProceduralRelevanceAssessment:
        """Is this section procedural content?  Fallback when rules
        are inconclusive."""
        ...

    def classify_section(
        self,
        section: Section,
    ) -> SectionClassificationResult:
        """Classify a section as setup/procedure/inspection/etc."""
        ...

    def interpret_procedural_steps(
        self,
        text: str,
        context: str,
    ) -> list[StepInterpretation]:
        """Extract procedural steps from unstructured text."""
        ...

    def interpret_requirements(
        self,
        text: str,
        context: str,
    ) -> list[RequirementInterpretation]:
        """Extract preliminary requirements from prose."""
        ...

    def interpret_references(
        self,
        text: str,
    ) -> list[ReferenceInterpretation]:
        """Extract cross-references (DM refs, figure refs, etc.)."""
        ...

    def classify_procedural_table(
        self,
        table: TableAsset,
    ) -> SectionClassificationResult:
        """Classify a table's role within the procedure."""
        ...


# ═══════════════════════════════════════════════════════════════════════
#  2. PROCEDURAL RULES ENGINE PORT
#
#  12 methods.  6 mirror shared signatures that can't be extracted
#  from RulesEnginePort without modifying it.  6 are procedural-only.
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class ProceduralRulesEnginePort(Protocol):
    """Deterministic rules for procedural mapping.

    Same contract as ``RulesEnginePort``:
      • Idempotent, side-effect free.
      • No LLM, no network, no persistence.
    """

    # ── Header / DM-code (mirrors RulesEnginePort, different types) ──

    def generate_record_id(self) -> str:
        """UUID or ULID.  Shared concept but not extractable from
        RulesEnginePort without refactoring it."""
        ...

    def build_dm_code(
        self,
        source: DocumentPipelineOutput,
        module_type: ProceduralModuleType,  # ← FaultMode in fault port
    ) -> DmCode:
        """DM-code construction with procedural info-code selection."""
        ...

    def determine_info_code(
        self,
        module_type: ProceduralModuleType,  # ← FaultMode in fault port
    ) -> str:
        """``"040"`` for PROCEDURAL, ``"041"`` for DESCRIPTIVE."""
        ...

    def resolve_issue_info(self) -> IssueInfo:
        ...

    def resolve_issue_date(self) -> IssueDate:
        ...

    def normalize_title(
        self,
        raw_title: str,
        module_type: ProceduralModuleType,  # ← FaultMode in fault port
    ) -> DmTitle:
        ...

    def default_language(self) -> Language:
        ...

    # ── Procedural-only heuristics ───────────────────────────────

    def procedural_relevance_keywords(self) -> frozenset[str]:
        """Keywords that indicate procedural content (e.g. "step",
        "install", "remove", "procedure")."""
        ...

    def procedural_relevant_section_types(self) -> frozenset[str]:
        """Section types inherently procedural (e.g. "maintenance",
        "installation")."""
        ...

    def classify_section_by_structure(
        self,
        section: Section,
    ) -> ProceduralSectionType | None:
        """Attempt rule-based section classification; ``None`` → ask LLM."""
        ...

    def normalize_step_number(self, raw_number: str) -> str:
        """Normalise "Step 1", "1.", "1)", "a." → canonical form."""
        ...

    def llm_confidence_threshold(self, task: str) -> float:
        """Minimum confidence for a given task.  Well-known keys:
        ``"procedural_relevance"``, ``"section_classification"``,
        ``"step_extraction"``, ``"requirement_extraction"``,
        ``"reference_extraction"``."""
        ...
