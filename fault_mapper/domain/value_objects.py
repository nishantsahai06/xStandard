"""Immutable value objects for the fault data module mapper.

All types are frozen dataclasses — they carry no identity and are
compared purely by value.  Three categories:

  A. S1000D structural value objects (DmCode, Language, IssueInfo, …)
     Represent fine-grained S1000D identification concepts.

  B. Mapping traceability value objects (FieldOrigin, MappingTrace)
     Record HOW each target field was produced and from WHERE.

  C. LLM interpretation results (FaultModeInterpretation, …)
     Intermediate products of the LLM interpreter port.
     These are NEVER written directly into the canonical output —
     the application-layer assembler merges them deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fault_mapper.domain.enums import (
    AuditEventType,
    FaultMode,
    MappingStrategy,
    ReconciliationOutcome,
    ReviewStatus,
    TableType,
    ValidationSeverity,
    ValidationStatus,
)


# ═══════════════════════════════════════════════════════════════════════
#  A.  S1000D STRUCTURAL VALUE OBJECTS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DmCode:
    """S1000D Data Module Code — the 11+ segment unique identifier.

    Every segment matches the canonical schema regex.  ``learn_code``
    and ``learn_event_code`` are optional S1000D extensions.
    """

    model_ident_code: str
    system_diff_code: str
    system_code: str
    sub_system_code: str
    sub_sub_system_code: str
    assy_code: str
    disassy_code: str
    disassy_code_variant: str
    info_code: str
    info_code_variant: str
    item_location_code: str
    learn_code: str | None = None
    learn_event_code: str | None = None

    def as_string(self) -> str:
        """Format as a human-readable DM-code string.

        Example: ``"TESTAC-A-29-00-00-00A-031A-A"``
        """
        return (
            f"{self.model_ident_code}-"
            f"{self.system_diff_code}-"
            f"{self.system_code}-"
            f"{self.sub_system_code}{self.sub_sub_system_code}-"
            f"{self.assy_code}-"
            f"{self.disassy_code}{self.disassy_code_variant}-"
            f"{self.info_code}{self.info_code_variant}-"
            f"{self.item_location_code}"
        )


@dataclass(frozen=True)
class Language:
    """ISO language + country code pair."""

    language_iso_code: str   # e.g. "en"
    country_iso_code: str    # e.g. "US"


@dataclass(frozen=True)
class IssueInfo:
    """S1000D issue number (exactly 3 digits) and in-work indicator (2 digits)."""

    issue_number: str   # "001"
    in_work: str        # "00"


@dataclass(frozen=True)
class IssueDate:
    """Year / month / day as zero-padded strings per S1000D convention."""

    year: str    # "2026"
    month: str   # "04"
    day: str     # "13"


@dataclass(frozen=True)
class DmTitle:
    """Data module title.  ``tech_name`` is mandatory per S1000D."""

    tech_name: str
    info_name: str | None = None
    info_name_variant: str | None = None


# ═══════════════════════════════════════════════════════════════════════
#  B.  MAPPING TRACEABILITY VALUE OBJECTS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FieldOrigin:
    """Records HOW a single target field was derived.

    Every non-trivial field in the canonical output should carry an
    origin so the validation / review pipeline can audit the mapping.

    Attributes
    ----------
    strategy : MappingStrategy
        DIRECT, RULE, or LLM.
    source_path : str
        JSON-path-like string into ``DocumentPipelineOutput``
        (e.g. ``"sections[2].chunks[0].chunk_text"``).
    confidence : float
        1.0 for DIRECT/RULE, 0.0–1.0 for LLM-derived values.
    source_chunk_id : str | None
        Pipeline chunk ID that was the primary evidence, if any.
    """

    strategy: MappingStrategy
    source_path: str
    confidence: float = 1.0
    source_chunk_id: str | None = None


@dataclass(frozen=True)
class MappingTrace:
    """Aggregate traceability snapshot for one complete mapping run.

    Created by the assembler once all sub-mappers have finished.
    Attached to the root ``S1000DFaultDataModule`` aggregate as a
    first-class citizen.

    Note: ``frozen=True`` prevents attribute re-assignment.  The inner
    collections are mutable by convention only — callers must not mutate
    a trace after construction.
    """

    field_origins: dict[str, FieldOrigin] = field(default_factory=dict)
    unmapped_sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mapped_at: str | None = None   # ISO 8601 timestamp, set by assembler


# ═══════════════════════════════════════════════════════════════════════
#  C.  LLM INTERPRETATION RESULTS (intermediate, never trusted directly)
#
#  Produced by the LLM interpreter port; consumed by the
#  application-layer mappers.  The assembler decides whether to accept
#  each interpretation based on confidence thresholds and rule checks.
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FaultModeInterpretation:
    """LLM assessment of whether sections describe fault-reporting or
    fault-isolation content."""

    mode: FaultMode
    confidence: float
    reasoning: str


@dataclass(frozen=True)
class FaultDescriptionInterpretation:
    """LLM-extracted fault description from unstructured text."""

    description: str
    system_name: str | None = None
    fault_code_suggestion: str | None = None
    fault_equipment: str | None = None
    fault_message: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class IsolationStepInterpretation:
    """LLM-extracted fault-isolation step from unstructured text.

    ``yes_next`` / ``no_next`` are step numbers for branch wiring;
    ``None`` means that branch terminates or is unknown.
    """

    step_number: int
    instruction: str
    question: str | None = None
    yes_next: int | None = None
    no_next: int | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class TableClassification:
    """LLM classification of a table's role inside the fault module."""

    role: TableType
    confidence: float
    reasoning: str


@dataclass(frozen=True)
class LruSruExtraction:
    """LLM-extracted LRU or SRU item from text or table content."""

    name: str
    short_name: str | None = None
    ident_number: str | None = None
    is_lru: bool = True
    confidence: float = 0.0


@dataclass(frozen=True)
class FaultRelevanceAssessment:
    """LLM assessment of whether a section contains fault-relevant content.

    Produced by the LLM interpreter port as a fallback when rule-based
    keyword / section-type heuristics are inconclusive.  The application
    layer uses the returned ``confidence`` against a configurable
    threshold to make the final include/exclude decision.
    """

    is_relevant: bool
    confidence: float
    reasoning: str


@dataclass(frozen=True)
class SchematicCorrelation:
    """LLM-assessed correlation between a schematic and fault descriptions.

    Produced by the LLM interpreter port when deterministic
    component-name matching and page-proximity heuristics fail to
    link a schematic diagram to specific fault descriptions.

    ``matched_descriptions`` are the fault-description strings the
    schematic is deemed relevant to.  ``matched_components`` are the
    component names from the schematic that drove the match.
    """

    matched_descriptions: list[str] = field(default_factory=list)
    matched_components: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""


# ═══════════════════════════════════════════════════════════════════════
#  D.  VALIDATION & REVIEW DECISION VALUE OBJECTS
#
#  Produced by the validation layer after assembly.  Consumed by the
#  review gate and (eventually) the persistence layer.
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ValidationIssue:
    """A single finding from a validation check.

    Carries enough context for the review gate and human reviewers
    to understand and act on the issue without re-running validation.

    Attributes
    ----------
    code : str
        Machine-readable issue identifier (e.g. ``"STRUCT-001"``).
        Codes are namespaced: ``STRUCT-*`` for structural issues,
        ``BIZ-*`` for business-rule issues.
    severity : ValidationSeverity
        ERROR, WARNING, or INFO.
    message : str
        Human-readable description of the issue.
    field_path : str | None
        Dot-delimited path to the offending field within the module
        (e.g. ``"header.dm_code.system_code"``).
    context : str | None
        Optional additional context (e.g. the offending value).
    """

    code: str
    severity: ValidationSeverity
    message: str
    field_path: str | None = None
    context: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity is ValidationSeverity.ERROR

    @property
    def is_warning(self) -> bool:
        return self.severity is ValidationSeverity.WARNING


@dataclass(frozen=True)
class ModuleValidationResult:
    """Aggregate result of all validation checks on one module.

    Two independent axes:
      - ``structural_issues`` from canonical structural validation.
      - ``business_issues`` from business-rule validation.

    The ``status`` is derived deterministically:
      any ERROR → the corresponding status (SCHEMA_FAILED or
      BUSINESS_RULE_FAILED);  warnings-only → REVIEW_REQUIRED;
      clean → APPROVED.
    """

    structural_issues: list[ValidationIssue] = field(default_factory=list)
    business_issues: list[ValidationIssue] = field(default_factory=list)
    status: ValidationStatus = ValidationStatus.PENDING

    @property
    def all_issues(self) -> list[ValidationIssue]:
        return list(self.structural_issues) + list(self.business_issues)

    @property
    def has_errors(self) -> bool:
        return any(i.is_error for i in self.all_issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.is_warning for i in self.all_issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.all_issues if i.is_error)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.all_issues if i.is_warning)


@dataclass(frozen=True)
class ReviewDecision:
    """Output of the review gate — whether the module can proceed.

    Attributes
    ----------
    review_status : ReviewStatus
        The decided review status.
    validation_status : ValidationStatus
        The decided validation status.
    reasons : list[str]
        Human-readable reasons for the decision.
    auto_approved : bool
        True if the module was auto-approved without human review.
    """

    review_status: ReviewStatus = ReviewStatus.NOT_REVIEWED
    validation_status: ValidationStatus = ValidationStatus.PENDING
    reasons: list[str] = field(default_factory=list)
    auto_approved: bool = False


# ═══════════════════════════════════════════════════════════════════════
#  E.  PERSISTENCE VALUE OBJECTS
#
#  Produced by the persistence service.  Wrap a serialised module
#  with metadata required for durable storage and retrieval.
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PersistenceEnvelope:
    """Wraps a serialised module dict with storage metadata.

    The persistence service builds this before handing off to the
    repository port.  The envelope is the single unit-of-write.

    Attributes
    ----------
    record_id : str
        The canonical module ``record_id`` (unique key in the store).
    collection : str
        Logical collection name (``"trusted"`` or ``"review"``).
    document : dict
        The JSON-serialised module (output of ``serialize_module``).
    validation_status : ValidationStatus
        Snapshot of the module's validation status at persist time.
    review_status : ReviewStatus
        Snapshot of the module's review status at persist time.
    mapping_version : str | None
        Version stamp from the mapping pipeline.
    stored_at : str | None
        ISO 8601 timestamp set by the persistence service.
    """

    record_id: str
    collection: str
    document: dict[str, object]
    validation_status: ValidationStatus = ValidationStatus.APPROVED
    review_status: ReviewStatus = ReviewStatus.NOT_REVIEWED  # noqa: E501
    mapping_version: str | None = None
    stored_at: str | None = None


@dataclass(frozen=True)
class PersistenceResult:
    """Outcome of a persistence operation.

    Attributes
    ----------
    success : bool
        True if the document was persisted without error.
    record_id : str
        The record that was (or was attempted to be) persisted.
    collection : str
        The target collection.
    stored_at : str | None
        ISO 8601 timestamp when the write completed (None on failure).
    error : str | None
        Human-readable error description on failure.
    """

    success: bool
    record_id: str
    collection: str
    stored_at: str | None = None
    error: str | None = None


# ═══════════════════════════════════════════════════════════════════════
#  F.  AUDIT LOG VALUE OBJECTS
#
#  Lightweight audit entries for recording review workflow events.
#  Stored separately from the main module documents for clean history.
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AuditEntry:
    """Immutable record of a review workflow event.

    Captures who did what, when, and why — enough context for
    compliance reporting without inflating the main module documents.

    Attributes
    ----------
    record_id : str
        The fault module ``record_id`` this event relates to.
    event_type : AuditEventType
        The kind of event (REVIEW_REJECTED, REVIEW_APPROVED).
    reason : str
        Human-readable reason for the action (may be empty for
        approvals).
    timestamp : str
        ISO 8601 UTC timestamp when the event was recorded.
    performed_by : str | None
        Identity of the actor (user ID, service name, etc.).
        None when not supplied by the caller.
    validation_status : ValidationStatus | None
        Snapshot of the module's validation status at event time.
    review_status : ReviewStatus | None
        Snapshot of the module's review status at event time.
    collection : str | None
        The collection the module was in at event time.
    """

    record_id: str
    event_type: AuditEventType
    reason: str
    timestamp: str
    performed_by: str | None = None
    validation_status: ValidationStatus | None = None
    review_status: ReviewStatus | None = None
    collection: str | None = None


# ═══════════════════════════════════════════════════════════════════════
#  G.  RECONCILIATION VALUE OBJECTS
#
#  Used by the reconciliation / sweep service to report what happened
#  during a sweep pass.  Frozen for immutability and audit safety.
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ReconciliationDetail:
    """Outcome detail for a single record in a reconciliation sweep.

    Attributes
    ----------
    record_id : str
        The fault module ``record_id`` that was examined.
    outcome : ReconciliationOutcome
        What happened: CLEANED, SKIPPED, or ERROR.
    reason : str
        Human-readable explanation (e.g. "Orphaned review entry deleted",
        "Conflicting content — skipped", "Delete failed: …").
    """

    record_id: str
    outcome: ReconciliationOutcome
    reason: str


@dataclass(frozen=True)
class ReconciliationReport:
    """Aggregate report for one reconciliation sweep pass.

    Attributes
    ----------
    total_review_scanned : int
        Number of review-collection records scanned.
    duplicates_found : int
        Records that exist in both review and trusted.
    duplicates_cleaned : int
        Orphaned review entries successfully deleted.
    duplicates_skipped : int
        Duplicates that were not safe to delete.
    errors : int
        Delete attempts that failed at the repository level.
    dry_run : bool
        If True, no deletes were actually performed.
    details : list[ReconciliationDetail]
        Per-record outcome details.
    """

    total_review_scanned: int = 0
    duplicates_found: int = 0
    duplicates_cleaned: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    dry_run: bool = False
    details: list[ReconciliationDetail] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
#  H.  BATCH PROCESSING VALUE OBJECTS
#
#  Used by the batch processing service to report per-item outcomes
#  and aggregate batch statistics.  Frozen for immutability.
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BatchItemResult:
    """Outcome of processing a single item within a batch.

    Attributes
    ----------
    source_id : str
        Identifier of the input document (``DocumentPipelineOutput.id``).
    success : bool
        True if the item was mapped, validated, and persisted without error.
    record_id : str | None
        The produced ``S1000DFaultDataModule.record_id``, if mapping succeeded.
    validation_status : str | None
        The module's validation status value string (e.g. ``"approved"``).
    review_status : str | None
        The module's review status value string (e.g. ``"not_reviewed"``).
    collection : str | None
        The target persistence collection (``"trusted"`` or ``"review"``).
    persisted : bool
        Whether the module was successfully written to storage.
    error : str | None
        Human-readable error description on failure.
    mode : str | None
        The fault mode value string (e.g. ``"fault_reporting"``).
    mapping_version : str | None
        Version stamp from the mapping pipeline.
    """

    source_id: str
    success: bool
    record_id: str | None = None
    validation_status: str | None = None
    review_status: str | None = None
    collection: str | None = None
    persisted: bool = False
    error: str | None = None
    mode: str | None = None
    mapping_version: str | None = None


@dataclass(frozen=True)
class BatchReport:
    """Aggregate result of a batch processing operation.

    Attributes
    ----------
    total : int
        Total number of items submitted.
    succeeded : int
        Items that completed the full pipeline without error.
    failed : int
        Items that failed at any stage (mapping, validation, persistence).
    persisted_trusted : int
        Items persisted to the trusted collection.
    persisted_review : int
        Items persisted to the review collection.
    not_persisted : int
        Items that were not persisted (ineligible status or failure).
    elapsed_ms : float
        Wall-clock time for the entire batch in milliseconds.
    items : list[BatchItemResult]
        Per-item outcome details.
    """

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    persisted_trusted: int = 0
    persisted_review: int = 0
    not_persisted: int = 0
    elapsed_ms: float = 0.0
    items: list[BatchItemResult] = field(default_factory=list)
