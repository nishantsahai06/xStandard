"""Procedural-specific target-side canonical models.

Source-side models (DocumentPipelineOutput, Section, Chunk, TableAsset,
ImageAsset, SchematicsItem, Metadata) are defined in
``fault_mapper.domain.models`` and shared across all module mappers.

Shared S1000D building blocks (Ref, NoteLike, TypedText, FigureRef,
CommonInfo, Provenance, Classification, XmlMeta) are also defined in
``fault_mapper.domain.models``.

This file defines the procedural-specific target models aligned to
the canonical procedural schema shape:

  Schema top-level:
    schemaVersion, moduleType, source, identAndStatusSection,
    content, validation, lineage

  Schema content.sections[]:
    sectionId, title, sectionOrder, sectionType, level,
    pageNumbers, rawSectionText, steps[], subSections[],
    figures[], tables[], references[]

  Schema proceduralStep:
    stepId, stepNumber, text, actionType, sourceChunkIds,
    warnings[], cautions[], notes[], expectedResult, references[]
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.procedural_enums import (
    ActionType,
    ProceduralModuleType,
    ProceduralSectionType,
    SecurityClassification,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    IssueDate,
    IssueInfo,
    Language,
    MappingTrace,
)
from fault_mapper.domain.procedural_value_objects import (
    DataOrigin,
    ProceduralConfidence,
    ResponsiblePartnerCompany,
    SourceSectionRef,
)

# Shared target building blocks — NOT fault-specific.
from fault_mapper.domain.models import (  # noqa: F401 — re-exports
    Classification,
    FigureRef,
    NoteLike,
    Provenance,
    TypedText,
    XmlMeta,
)


# ─── Procedural reference ───────────────────────────────────────────


@dataclass
class ProceduralReference:
    """Cross-reference within a procedural section or step.

    Schema-aligned to ``content.sections[].references[]`` and
    ``proceduralStep.references[]``.
    """

    ref_type: str = "dm_ref"  # "dm_ref"|"figure_ref"|"table_ref"|"external"
    target_dm_code: str | None = None
    target_id: str | None = None
    label: str | None = None


# ─── Procedural table reference ─────────────────────────────────────


@dataclass
class ProceduralTableRef:
    """Reference to a table within a procedural section.

    Schema-aligned to ``content.sections[].tables[]``.
    """

    table_id: str | None = None
    caption: str | None = None
    source_table_id: str | None = None


# ─── Procedural requirement item ────────────────────────────────────


@dataclass
class ProceduralRequirementItem:
    """One preliminary requirement item.

    Schema-aligned to ``content.preliminaryRequirements[]``.
    Covers personnel, equipment, supply, spare, and safety
    requirement types in a single flat structure.
    """

    requirement_type: str  # "personnel"|"equipment"|"supply"|"spare"|"safety"
    name: str | None = None
    ident_number: str | None = None
    quantity: float = 0.0
    unit: str | None = None
    role: str | None = None
    skill_level: str | None = None
    safety_text: str | None = None
    source_table_id: str | None = None


# ─── Procedural step (recursive) ────────────────────────────────────


@dataclass
class ProceduralStep:
    """One procedural step — may contain nested sub-steps.

    Schema-aligned to ``proceduralStep``:
      stepId, stepNumber, text, actionType, sourceChunkIds,
      warnings[], cautions[], notes[], expectedResult, references[]
    """

    step_id: str | None = None
    step_number: str = ""
    text: str = ""
    action_type: ActionType = ActionType.GENERAL
    source_chunk_ids: list[str] = field(default_factory=list)
    warnings: list[NoteLike] = field(default_factory=list)
    cautions: list[NoteLike] = field(default_factory=list)
    notes: list[NoteLike] = field(default_factory=list)
    expected_result: str | None = None
    references: list[ProceduralReference] = field(default_factory=list)
    sub_steps: list[ProceduralStep] = field(default_factory=list)


# ─── Procedural section (recursive) ─────────────────────────────────


@dataclass
class ProceduralSection:
    """One logical section within the procedure.

    Schema-aligned to ``content.sections[]``:
      sectionId, title, sectionOrder, sectionType, level,
      pageNumbers, rawSectionText, steps[], subSections[],
      figures[], tables[], references[]
    """

    section_id: str | None = None
    title: str = ""
    section_order: int = 0
    section_type: ProceduralSectionType = ProceduralSectionType.GENERAL
    level: int = 1
    page_numbers: list[int] = field(default_factory=list)
    raw_section_text: str | None = None
    steps: list[ProceduralStep] = field(default_factory=list)
    sub_sections: list[ProceduralSection] = field(default_factory=list)
    figures: list[FigureRef] = field(default_factory=list)
    tables: list[ProceduralTableRef] = field(default_factory=list)
    references: list[ProceduralReference] = field(default_factory=list)
    source_section_id: str | None = None


# ─── Procedural content ─────────────────────────────────────────────


@dataclass
class ProceduralContent:
    """Content section of the procedural data module.

    Schema-aligned to ``content``:
      preliminaryRequirements[], warnings[], cautions[],
      notes[], sections[]
    """

    preliminary_requirements: list[ProceduralRequirementItem] = field(
        default_factory=list,
    )
    warnings: list[NoteLike] = field(default_factory=list)
    cautions: list[NoteLike] = field(default_factory=list)
    notes: list[NoteLike] = field(default_factory=list)
    sections: list[ProceduralSection] = field(default_factory=list)


# ─── Procedural header (identAndStatusSection) ──────────────────────


@dataclass
class ProceduralHeader:
    """Identification and status section of the procedural data module.

    Schema-aligned to ``identAndStatusSection``:
      dmCode, language, issueInfo, issueDate, dmTitle,
      securityClassification, responsiblePartnerCompany,
      origin, sns (optional), brex (optional)
    """

    dm_code: DmCode
    language: Language
    issue_info: IssueInfo
    issue_date: IssueDate
    dm_title: DmTitle
    security_classification: SecurityClassification = SecurityClassification.UNCLASSIFIED
    responsible_partner_company: ResponsiblePartnerCompany = field(
        default_factory=ResponsiblePartnerCompany,
    )
    origin: DataOrigin = field(default_factory=DataOrigin)
    sns: str | None = None
    brex: str | None = None


# ─── Procedural validation ──────────────────────────────────────────


@dataclass
class ProceduralValidationResults:
    """Validation results for a procedural module.

    Schema-aligned to ``validation``:
      schemaValid, businessRuleValid, status, errors[], warnings[]

    Lightweight for Chunk 2 — full validator service deferred.
    """

    schema_valid: bool | None = None
    business_rule_valid: bool | None = None
    status: ValidationStatus = ValidationStatus.PENDING
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ─── Procedural lineage ─────────────────────────────────────────────


@dataclass
class ProceduralLineage:
    """Mapping lineage for the procedural module.

    Schema-aligned to ``lineage``:
      mappedBy, mappedAt, mappingRulesetVersion, mappingMethod,
      sourceSections[], confidence
    """

    mapped_by: str = ""
    mapped_at: str = ""
    mapping_ruleset_version: str = ""
    mapping_method: str = ""
    source_sections: list[SourceSectionRef] = field(default_factory=list)
    confidence: ProceduralConfidence = field(
        default_factory=ProceduralConfidence,
    )


# ═══════════════════════════════════════════════════════════════════════
#  ROOT AGGREGATE
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class S1000DProceduralDataModule:
    """Root aggregate — one canonical S1000D procedural data module.

    Schema-aligned top-level fields:
      schemaVersion, moduleType, source, identAndStatusSection,
      content, validation, lineage

    Plus pipeline-internal fields:
      record_id, record_type, mapping_version, review_status,
      classification, trace, xml_meta
    """

    # ── Identity (pipeline-internal) ─────────────────────────────
    record_id: str
    record_type: str = field(
        default="S1000D_ProceduralDataModule", init=False,
    )

    # ── Schema top-level fields ──────────────────────────────────
    schema_version: str = "1.0.0"
    module_type: ProceduralModuleType = ProceduralModuleType.PROCEDURAL
    source: Provenance | None = None
    ident_and_status_section: ProceduralHeader | None = None
    content: ProceduralContent = field(default_factory=ProceduralContent)
    validation: ProceduralValidationResults | None = None
    lineage: ProceduralLineage | None = None

    # ── Pipeline trust metadata ──────────────────────────────────
    mapping_version: str | None = None
    review_status: ReviewStatus = ReviewStatus.NOT_REVIEWED
    classification: Classification | None = None
    trace: MappingTrace | None = None
    xml_meta: XmlMeta | None = None

    # ── Domain convenience ───────────────────────────────────────

    @property
    def is_procedural(self) -> bool:
        return self.module_type is ProceduralModuleType.PROCEDURAL

    @property
    def is_descriptive(self) -> bool:
        return self.module_type is ProceduralModuleType.DESCRIPTIVE

    @property
    def is_reviewed(self) -> bool:
        return self.review_status is ReviewStatus.APPROVED

    @property
    def total_steps(self) -> int:
        """Recursive step count across all sections."""
        return sum(
            _count_steps(s.steps) for s in self.content.sections
        )

    @property
    def total_sections(self) -> int:
        """Recursive section count."""
        return sum(
            _count_sections(s) for s in self.content.sections
        )


# ── Module-level helpers ─────────────────────────────────────────────


def _count_steps(steps: list[ProceduralStep]) -> int:
    """Recursively count all steps including sub-steps."""
    total = len(steps)
    for step in steps:
        total += _count_steps(step.sub_steps)
    return total


def _count_sections(section: ProceduralSection) -> int:
    """Recursively count a section and all sub-sections."""
    total = 1
    for sub in section.sub_sections:
        total += _count_sections(sub)
    return total
