"""Domain models for the fault data module mapper.

Organised into two clearly separated sections:

  SECTION A — SOURCE-SIDE MODELS
    Represent the normalised output of the document-extraction pipeline
    (``DocumentPipelineOutput`` and its nested parts).  These are the
    INPUT to the mapper.

  SECTION B — TARGET-SIDE CANONICAL MODELS
    Represent the S1000D canonical fault data module that the mapper
    PRODUCES.  Aligned 1-to-1 with ``fault_data_module.schema.json``
    so that serialisation to the canonical JSON is a mechanical step.

Naming conventions:
  Source models → pipeline-oriented names (Section, Chunk, TableAsset, …)
  Target models → S1000D-oriented names  (FaultEntry, IsolationStep, …)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fault_mapper.domain.enums import (
    ClassificationMethod,
    FaultEntryType,
    FaultMode,
    NoteLikeKind,
    ReviewStatus,
    ValidationOutcome,
    ValidationStatus,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    IssueDate,
    IssueInfo,
    Language,
    MappingTrace,
)


# ═══════════════════════════════════════════════════════════════════════
#
#  SECTION A — SOURCE-SIDE MODELS
#
#  These model the normalised pipeline output that enters the mapper.
#  Order: leaf types first, composite types last.
#
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class SchematicComponent:
    """One labelled component identified inside a schematic diagram."""

    name: str
    component_type: str | None = None
    reference_designator: str | None = None


@dataclass
class SchematicsItem:
    """A schematic diagram extracted from the source document."""

    page_number: int
    image_metadata: dict[str, Any] = field(default_factory=dict)
    components: list[SchematicComponent] = field(default_factory=list)
    source_path: str | None = None
    id: str | None = None


@dataclass
class Chunk:
    """One semantic chunk inside a section."""

    chunk_text: str
    original_text: str
    contextual_prefix: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    id: str | None = None


@dataclass
class ImageAsset:
    """An image extracted from a section."""

    caption: str | None = None
    page_number: int | None = None
    figure_label: str | None = None
    isometric: bool = False
    summaries: list[str] = field(default_factory=list)
    source_path: str | None = None
    embedding: list[float] | None = None
    id: str | None = None


@dataclass
class TableAsset:
    """A table extracted from a section."""

    caption: str | None = None
    page_number: int | None = None
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    markdown_summary: str | None = None
    embedding: list[float] | None = None
    id: str | None = None


@dataclass
class Section:
    """One logical section of the extracted document."""

    section_title: str
    section_order: int
    section_type: str
    section_text: str
    level: int
    page_numbers: list[int] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)
    tables: list[TableAsset] = field(default_factory=list)
    id: str | None = None


@dataclass
class Metadata:
    """Upload and extraction metadata from the pipeline."""

    upload_metadata: dict[str, Any] = field(default_factory=dict)
    extraction_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentPipelineOutput:
    """Root source model — the normalised output of the document-extraction
    pipeline.  This is the single input to the fault-mapping use case."""

    id: str
    full_text: str
    file_name: str
    file_type: str
    source_path: str
    metadata: Metadata
    sections: list[Section] = field(default_factory=list)
    schematics: list[SchematicsItem] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
#
#  SECTION B — TARGET-SIDE CANONICAL MODELS
#
#  These model the canonical S1000D fault data module that the mapper
#  produces.  Sub-sections are ordered bottom-up so that every type is
#  defined before its first use.
#
# ═══════════════════════════════════════════════════════════════════════


# ─── B.1  Shared building blocks ─────────────────────────────────────


@dataclass
class Ref:
    """Cross-reference to another data module or internal target."""

    type: str
    target_dm_code: str | None = None
    target_id: str | None = None
    label: str | None = None


@dataclass
class ApplicRef:
    """Applicability reference."""

    applicability_id: str | None = None
    label: str | None = None


@dataclass
class NoteLike:
    """Warning, caution, note, or remark with source-chunk provenance."""

    kind: NoteLikeKind
    text: str
    source_chunk_id: str | None = None


@dataclass
class TypedText:
    """Text with optional provenance.

    Used for paragraphs, requirement conditions, and any other simple
    text block that needs to track its source chunk.
    """

    text: str
    source_chunk_id: str | None = None


@dataclass
class FigureRef:
    """Reference to a figure / graphic."""

    figure_id: str | None = None
    caption: str | None = None


@dataclass
class CommonInfo:
    """Shared introductory information block."""

    title: str | None = None
    paragraphs: list[TypedText] = field(default_factory=list)
    figures: list[FigureRef] = field(default_factory=list)


# ─── B.2  Requirements blocks ────────────────────────────────────────


@dataclass
class RequiredPerson:
    """Personnel requirement."""

    role: str | None = None
    count: int = 1
    skill_level: str | None = None


@dataclass
class ItemRequirement:
    """Equipment, supply, or spare-part requirement."""

    name: str | None = None
    ident_number: str | None = None
    quantity: float = 0
    unit: str | None = None
    source_table_id: str | None = None


@dataclass
class ReqCondGroup:
    """Required-conditions group."""

    conditions: list[TypedText] = field(default_factory=list)


@dataclass
class ReqSafety:
    """Safety-related warnings, cautions, and notes."""

    warnings: list[NoteLike] = field(default_factory=list)
    cautions: list[NoteLike] = field(default_factory=list)
    notes: list[NoteLike] = field(default_factory=list)


@dataclass
class PreliminaryRequirements:
    """Preliminary requirements block (S1000D ``preliminaryRqmts``).

    Captures everything a technician needs before starting work.
    """

    req_cond_group: ReqCondGroup = field(default_factory=ReqCondGroup)
    req_support_equips: list[ItemRequirement] = field(default_factory=list)
    req_supplies: list[ItemRequirement] = field(default_factory=list)
    req_spares: list[ItemRequirement] = field(default_factory=list)
    req_safety: ReqSafety = field(default_factory=ReqSafety)
    production_maint_data: list[TypedText] = field(default_factory=list)
    req_persons: list[RequiredPerson] = field(default_factory=list)
    req_tech_info_group: list[Ref] = field(default_factory=list)


@dataclass
class CloseRequirements:
    """Close-up requirements block (S1000D ``closeRqmts``).

    Mirrors ``PreliminaryRequirements`` for post-repair actions.
    """

    req_cond_group: ReqCondGroup = field(default_factory=ReqCondGroup)
    req_support_equips: list[ItemRequirement] = field(default_factory=list)
    req_supplies: list[ItemRequirement] = field(default_factory=list)
    req_spares: list[ItemRequirement] = field(default_factory=list)
    req_safety: ReqSafety = field(default_factory=ReqSafety)


# ─── B.3  LRU / SRU / Repair hierarchy ──────────────────────────────


@dataclass
class FunctionalItemRef:
    """Reference to a functional-item number."""

    functional_item_number: str
    functional_item_type: str | None = None


@dataclass
class Lru:
    """Line Replaceable Unit."""

    name: str | None = None
    short_name: str | None = None
    ident_number: str | None = None
    part_ref: Ref | None = None
    functional_item_ref: FunctionalItemRef | None = None


@dataclass
class Sru:
    """Shop Replaceable Unit."""

    name: str | None = None
    short_name: str | None = None
    ident_number: str | None = None
    part_ref: Ref | None = None
    functional_item_ref: FunctionalItemRef | None = None


@dataclass
class Repair:
    """Repair action defined by one or more cross-references."""

    refs: list[Ref] = field(default_factory=list)


# ─── B.4  Fault detection and locate-and-repair ─────────────────────


@dataclass
class DetectedSruItem:
    """SRU-level detection information."""

    srus: list[Sru] = field(default_factory=list)
    fault_probability: str | float | None = None
    remarks: str | None = None


@dataclass
class DetectedLruItem:
    """LRU-level detection information (may contain nested SRU)."""

    lrus: list[Lru] = field(default_factory=list)
    fault_probability: str | float | None = None
    remarks: str | None = None
    detected_sru_item: DetectedSruItem | None = None


@dataclass
class DetectionInfo:
    """Fault-detection information block."""

    detected_lru_item: DetectedLruItem = field(default_factory=DetectedLruItem)
    detection_type: str | None = None


@dataclass
class LocateAndRepairSruItem:
    """SRU-level locate-and-repair information."""

    srus: list[Sru] = field(default_factory=list)
    fault_probability: str | float | None = None
    repair: Repair | None = None
    remarks: str | None = None


@dataclass
class LocateAndRepairLruItem:
    """LRU-level locate-and-repair information (may contain nested SRU)."""

    lrus: list[Lru] = field(default_factory=list)
    fault_probability: str | float | None = None
    repair: Repair | None = None
    remarks: str | None = None
    locate_and_repair_sru_item: LocateAndRepairSruItem | None = None


@dataclass
class LocateAndRepair:
    """Locate-and-repair block for a fault entry."""

    locate_and_repair_lru_item: LocateAndRepairLruItem = field(
        default_factory=LocateAndRepairLruItem,
    )


# ─── B.5  Fault description ─────────────────────────────────────────


@dataclass
class DetailedFaultDescription:
    """Detailed sub-fields of a fault description (S1000D ``detailedFaultDescr``)."""

    view_location: str | None = None
    system_location: str | None = None
    system_name: str | None = None
    faulty_sub_system: str | None = None
    system_ident: str | None = None
    system_position: str | None = None
    fault_equip: str | None = None
    fault_message_indication: str | None = None
    fault_message_body: str | None = None
    fault_cond: str | None = None


@dataclass
class FaultDescription:
    """Fault description (mandatory ``descr`` + optional detail block)."""

    descr: str
    detailed: DetailedFaultDescription | None = None


# ─── B.6  Fault entry ────────────────────────────────────────────────


@dataclass
class FaultEntry:
    """One fault entry inside a faultReporting block.

    ``entry_type`` drives conditional requirements: for example
    ``ISOLATED_FAULT`` requires ``id``, ``fault_code``,
    ``fault_descr``, and ``locate_and_repair``.
    """

    entry_type: FaultEntryType
    id: str | None = None
    fault_code: str | None = None
    fault_descr: FaultDescription | None = None
    detection_info: DetectionInfo | None = None
    locate_and_repair: LocateAndRepair | None = None
    remarks: str | None = None


# ─── B.7  Fault reporting content ────────────────────────────────────


@dataclass
class FaultReportingContent:
    """Fault-reporting content block (S1000D ``faultReporting``).

    Active when ``FaultMode.FAULT_REPORTING`` is the module mode.
    """

    fault_entries: list[FaultEntry] = field(default_factory=list)
    common_info: CommonInfo | None = None
    preliminary_rqmts: PreliminaryRequirements | None = None
    close_rqmts: CloseRequirements | None = None


# ─── B.8  Fault isolation content (recursive decision tree) ─────────


@dataclass
class IsolationResult:
    """Terminal result of a fault-isolation decision branch."""

    fault_confirmed: bool = False
    faulty_item: Lru | None = None
    repair_action: str | None = None
    repair_ref: Ref | None = None


@dataclass
class IsolationStepBranch:
    """One branch (YES or NO) of a fault-isolation decision point.

    Contains either nested ``next_steps`` (continuing the tree) or a
    terminal ``result``, or both.
    """

    next_steps: list[IsolationStep] = field(default_factory=list)
    result: IsolationResult | None = None


@dataclass
class IsolationStep:
    """Recursive fault-isolation step with yes/no branching.

    Maps to S1000D ``isolationStep`` → ``isolationStepQuestion``
    → ``yesGroup`` / ``noGroup``.  The ``question`` field drives the
    branch: if present, ``yes_group`` and ``no_group`` carry the
    respective sub-trees.
    """

    step_number: int
    instruction: str
    question: str | None = None
    yes_group: IsolationStepBranch | None = None
    no_group: IsolationStepBranch | None = None
    decision: str | None = None
    source_chunk_id: str | None = None
    refs: list[Ref] = field(default_factory=list)


@dataclass
class FaultIsolationContent:
    """Fault-isolation content block (S1000D ``faultIsolation``).

    Active when ``FaultMode.FAULT_ISOLATION`` is the module mode.
    """

    fault_isolation_steps: list[IsolationStep] = field(default_factory=list)
    common_info: CommonInfo | None = None
    preliminary_rqmts: PreliminaryRequirements | None = None
    close_rqmts: CloseRequirements | None = None


# ─── B.9  Content wrapper ────────────────────────────────────────────


@dataclass
class FaultContent:
    """Content section of the fault data module.

    Wraps the mode-specific sub-block and shared elements (refs,
    warnings/cautions, top-level prelim requirements).  The
    ``allOf/if-then`` constraint in the schema means that exactly one
    of ``fault_reporting`` / ``fault_isolation`` is non-null.
    """

    refs: list[Ref] = field(default_factory=list)
    warnings_and_cautions: list[NoteLike] = field(default_factory=list)
    applic_refs: list[ApplicRef] = field(default_factory=list)
    preliminary_rqmts: PreliminaryRequirements | None = None
    fault_reporting: FaultReportingContent | None = None
    fault_isolation: FaultIsolationContent | None = None

    @property
    def active_mode(self) -> FaultMode | None:
        """Return the active mode based on which sub-block is populated."""
        if self.fault_reporting is not None:
            return FaultMode.FAULT_REPORTING
        if self.fault_isolation is not None:
            return FaultMode.FAULT_ISOLATION
        return None


# ─── B.10  Header, classification, and metadata ─────────────────────


@dataclass
class FaultHeader:
    """Identification and status section of the data module."""

    dm_code: DmCode
    language: Language
    issue_info: IssueInfo
    issue_date: IssueDate
    dm_title: DmTitle


@dataclass
class Classification:
    """Classification metadata for the source-to-S1000D mapping."""

    domain: str = "S1000D"
    confidence: float = 0.0
    method: ClassificationMethod = ClassificationMethod.RULES


@dataclass
class ValidationResults:
    """Granular outcomes of individual validation checks."""

    schema: ValidationOutcome = ValidationOutcome.NOT_RUN
    completeness: ValidationOutcome = ValidationOutcome.NOT_RUN
    xsd_alignment: ValidationOutcome = ValidationOutcome.NOT_RUN
    business_rules: ValidationOutcome = ValidationOutcome.NOT_RUN
    semantic_confidence: float = 0.0


@dataclass
class XmlMeta:
    """XML serialisation metadata (post-mapping, pre-CSDB storage)."""

    id: str | None = None
    schema_source: str | None = None
    serialization_target: str | None = None


# ─── B.11  Provenance ────────────────────────────────────────────────


@dataclass
class Provenance:
    """First-class source-lineage record.

    Links the canonical target module back to every element of the
    original ``DocumentPipelineOutput`` that contributed to it.
    """

    source_document_id: str
    source_section_ids: list[str] = field(default_factory=list)
    source_pages: list[int] = field(default_factory=list)
    source_chunk_ids: list[str] = field(default_factory=list)
    source_table_ids: list[str] = field(default_factory=list)
    source_image_ids: list[str] = field(default_factory=list)
    source_schematic_refs: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
#  ROOT AGGREGATE — S1000DFaultDataModule
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class S1000DFaultDataModule:
    """Root aggregate — one canonical S1000D fault data module record.

    This is the **single output type** produced by the mapping pipeline.
    It must always be assembled deterministically by the application-layer
    assembler; no LLM is permitted to construct this object directly.

    Three trust axes are tracked:
      1. ``validation_status`` — automated pipeline checks
      2. ``review_status``     — human sign-off
      3. ``trace``             — per-field mapping provenance
    """

    # ── Identity ─────────────────────────────────────────────────
    record_id: str
    record_type: str = field(default="S1000D_FaultDataModule", init=False)

    # ── Core structural content ──────────────────────────────────
    mode: FaultMode = FaultMode.FAULT_REPORTING
    header: FaultHeader | None = None
    content: FaultContent = field(default_factory=FaultContent)

    # ── Provenance (WHERE did the data come from?) ───────────────
    provenance: Provenance | None = None

    # ── Staged trust ─────────────────────────────────────────────
    mapping_version: str | None = None
    validation_status: ValidationStatus = ValidationStatus.PENDING
    review_status: ReviewStatus = ReviewStatus.NOT_REVIEWED
    validation_results: ValidationResults | None = None

    # ── Mapping audit trail (HOW was each field produced?) ───────
    classification: Classification | None = None
    trace: MappingTrace | None = None

    # ── Serialisation hints ──────────────────────────────────────
    xml_meta: XmlMeta | None = None

    # ── Domain convenience methods ───────────────────────────────

    @property
    def is_fault_reporting(self) -> bool:
        """True if this module is in fault-reporting mode."""
        return self.mode is FaultMode.FAULT_REPORTING

    @property
    def is_fault_isolation(self) -> bool:
        """True if this module is in fault-isolation mode."""
        return self.mode is FaultMode.FAULT_ISOLATION

    @property
    def is_reviewed(self) -> bool:
        """True if a human reviewer has approved this module."""
        return self.review_status is ReviewStatus.APPROVED

    @property
    def is_trusted(self) -> bool:
        """True if both automated validation and human review have passed."""
        return (
            self.validation_status in (ValidationStatus.APPROVED, ValidationStatus.STORED)
            and self.review_status is ReviewStatus.APPROVED
        )
