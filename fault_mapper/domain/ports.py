"""Domain ports — abstract interfaces for external capabilities.

These protocols define what the application layer NEEDS but never HOW
it is provided.  Concrete implementations live in the adapters layer
and are injected via the infrastructure factory.

Design principles
─────────────────
• ``typing.Protocol`` with ``@runtime_checkable`` so that:
    – Adapters satisfy the contract via structural sub-typing (no
      inheritance required).
    – The infrastructure factory can perform basic ``isinstance``
      sanity checks at wiring time.
• Every port is narrow and cohesive — no god interfaces.
• All signatures use domain types only — no HTTP responses, vendor
  SDK objects, database sessions, or other infrastructure leaks.
• All methods are synchronous.  Async concerns are an adapter-layer
  detail; if an adapter needs to call an async API it should bridge
  internally (e.g. ``asyncio.run``).

Port inventory
──────────────
1. ``LlmInterpreterPort``       — semantic interpretation via LLM
                                   (7 methods)
2. ``RulesEnginePort``           — deterministic rules & configuration
                                   (14 methods, grouped by concern)
3. ``MappingReviewPolicyPort``   — review-policy boundary hook
                                   (1 method, optional)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fault_mapper.domain.enums import (
    FaultMode,
    ReviewStatus,
    TableType,
)
from fault_mapper.domain.models import (
    DocumentPipelineOutput,
    SchematicsItem,
    Section,
    TableAsset,
)
from fault_mapper.domain.value_objects import (
    AuditEntry,
    DmCode,
    DmTitle,
    FaultDescriptionInterpretation,
    FaultModeInterpretation,
    FaultRelevanceAssessment,
    IsolationStepInterpretation,
    IssueDate,
    IssueInfo,
    Language,
    LruSruExtraction,
    MappingTrace,
    PersistenceEnvelope,
    PersistenceResult,
    SchematicCorrelation,
    TableClassification,
)


# ═══════════════════════════════════════════════════════════════════════
#  1. LLM SEMANTIC INTERPRETATION PORT
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class LlmInterpreterPort(Protocol):
    """Port for LLM-based semantic interpretation.

    Implementations talk to an LLM (OpenAI, Anthropic, local, …).
    All return types are intermediate value objects — NEVER raw
    target-model instances.  The application layer is responsible
    for deciding whether to trust and incorporate these results.

    Contract
    --------
    • Every method returns a typed interpretation / value object.
    • No method may construct or return a canonical target model
      (``S1000DFaultDataModule`` or any of its target-side children).
    • Implementations MUST be stateless between calls — no
      conversational memory across method invocations.
    • Implementations SHOULD populate ``reasoning`` in their return
      objects so the mapping trace can carry audit context.
    """

    # ── Section-level relevance assessment ────────────────────────
    # Purpose  : LLM interpretation (fallback)
    # Used by  : FaultSectionSelector — when rule-based keyword /
    #            section-type heuristics are inconclusive.

    def assess_fault_relevance(
        self,
        section: Section,
    ) -> FaultRelevanceAssessment:
        """Assess whether a section contains fault-relevant content.

        Parameters
        ----------
        section : Section
            A single section from the pipeline output, including its
            title, text, and any nested chunks / tables / images.

        Returns
        -------
        FaultRelevanceAssessment
            ``is_relevant``, ``confidence``, and ``reasoning``.
            The application layer compares ``confidence`` against
            the rules engine's threshold to make the final decision.
        """
        ...

    # ── Mode determination ────────────────────────────────────────
    # Purpose  : LLM interpretation
    # Used by  : FaultModeRouter — after the rule pass returns None.

    def interpret_fault_mode(
        self,
        sections: list[Section],
    ) -> FaultModeInterpretation:
        """Determine whether sections describe fault-reporting or
        fault-isolation content.

        Parameters
        ----------
        sections : list[Section]
            Pre-filtered fault-relevant sections only.

        Returns
        -------
        FaultModeInterpretation
            ``mode``, ``confidence``, and ``reasoning``.
        """
        ...

    # ── Fault description extraction ──────────────────────────────
    # Purpose  : LLM interpretation
    # Used by  : FaultReportingMapper

    def interpret_fault_descriptions(
        self,
        text: str,
        context: str,
    ) -> list[FaultDescriptionInterpretation]:
        """Extract structured fault descriptions from unstructured text.

        Parameters
        ----------
        text : str
            The primary prose to analyse (typically section or chunk
            text).
        context : str
            Surrounding document context (section title, neighbouring
            text, document summary) to help disambiguation.

        Returns
        -------
        list[FaultDescriptionInterpretation]
            Zero or more fault descriptions with optional detail
            fields (``system_name``, ``fault_code_suggestion``,
            ``fault_equipment``, ``fault_message``).
        """
        ...

    # ── Isolation step extraction ─────────────────────────────────
    # Purpose  : LLM interpretation
    # Used by  : FaultIsolationMapper

    def interpret_isolation_steps(
        self,
        text: str,
        context: str,
    ) -> list[IsolationStepInterpretation]:
        """Extract fault-isolation decision steps from prose text.

        Parameters
        ----------
        text : str
            The troubleshooting / isolation procedure text.
        context : str
            Surrounding document context for disambiguation.

        Returns
        -------
        list[IsolationStepInterpretation]
            Flat steps with branch hints (``yes_next`` / ``no_next``).
            The application layer wires them into the recursive
            ``IsolationStep`` → ``IsolationStepBranch`` tree.
        """
        ...

    # ── Table classification ──────────────────────────────────────
    # Purpose  : LLM interpretation (fallback)
    # Used by  : FaultTableClassifier — when rule-based header
    #            matching returns None.

    def classify_table(
        self,
        table: TableAsset,
    ) -> TableClassification:
        """Classify a table's role within the fault module.

        Parameters
        ----------
        table : TableAsset
            A table extracted from the pipeline, including headers,
            rows, caption, and optional markdown summary.

        Returns
        -------
        TableClassification
            ``role`` (``TableType``), ``confidence``, ``reasoning``.
        """
        ...

    # ── LRU / SRU extraction ─────────────────────────────────────
    # Purpose  : LLM interpretation
    # Used by  : FaultReportingMapper, FaultIsolationMapper

    def extract_lru_sru(
        self,
        text: str,
    ) -> list[LruSruExtraction]:
        """Extract LRU / SRU item candidates from prose or table text.

        Parameters
        ----------
        text : str
            Free-form text or a serialised table (e.g. Markdown)
            that may mention replaceable units.

        Returns
        -------
        list[LruSruExtraction]
            Candidate items.  The application layer validates,
            deduplicates, and maps them to canonical ``Lru`` / ``Sru``
            target models.
        """
        ...

    # ── Schematic correlation (fallback) ──────────────────────────
    # Purpose  : LLM interpretation (fallback)
    # Used by  : FaultSchematicCorrelator — when deterministic
    #            component-name / page-proximity matching is
    #            insufficient.

    def correlate_schematic(
        self,
        schematic: SchematicsItem,
        fault_descriptions: list[str],
    ) -> SchematicCorrelation:
        """Correlate a schematic diagram with fault descriptions.

        Parameters
        ----------
        schematic : SchematicsItem
            A schematic extracted from the pipeline, including its
            components, page number, and image metadata.
        fault_descriptions : list[str]
            Plain-text fault descriptions already extracted by the
            reporting mapper.

        Returns
        -------
        SchematicCorrelation
            ``matched_descriptions``, ``matched_components``,
            ``confidence``, ``reasoning``.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════
#  2. DETERMINISTIC RULES / CONFIGURATION PORT
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class RulesEnginePort(Protocol):
    """Port for deterministic, auditable business rules and configuration.

    All outputs are fully reproducible — same inputs always produce
    the same outputs.  Implementations may read configuration files,
    environment variables, or in-memory config objects but MUST NOT
    call LLMs, access databases, or perform network I/O.

    Contract
    --------
    • Every method is idempotent and side-effect free.
    • This is NOT a persistence port.
    • This is NOT a validation port.
    • This is NOT an LLM port — no randomness, no generative calls.

    Method groups
    -------------
    A. Header defaults / DM-code assembly  (7 methods)
    B. Section & mode heuristics            (3 methods)
    C. Table heuristics                     (2 methods)
    D. Threshold / configuration lookup     (1 method)
    E. Fault-code derivation                (1 method)
    """

    # ── A. Header defaults / DM-code assembly ─────────────────────
    # Purpose  : deterministic rules
    # Used by  : FaultHeaderBuilder, FaultModuleAssembler (record_id)

    def generate_record_id(self) -> str:
        """Generate a unique record identifier (e.g. UUID v4, ULID).

        Called once per mapping run by the orchestrating use case.
        """
        ...

    def build_dm_code(
        self,
        source: DocumentPipelineOutput,
        mode: FaultMode,
    ) -> DmCode:
        """Construct the S1000D data-module code from source metadata
        and the resolved fault mode.

        The implementation maps pipeline metadata fields (aircraft
        model, ATA chapter, system identifiers, …) into the 11+
        segment DM-code structure, including the info code and
        item-location code.
        """
        ...

    def determine_info_code(self, mode: FaultMode) -> str:
        """Return the 3-character S1000D infoCode for the given mode.

        Typical mappings:
          ``FAULT_REPORTING`` → ``"031"``
          ``FAULT_ISOLATION`` → ``"032"``

        Exact values are deployment-configurable.
        """
        ...

    def resolve_issue_info(self) -> IssueInfo:
        """Return the current issue number and in-work indicator.

        Issue number is exactly 3 digits (e.g. ``"001"``); in-work
        is exactly 2 digits (e.g. ``"00"``).
        """
        ...

    def resolve_issue_date(self) -> IssueDate:
        """Return today's date formatted per S1000D convention
        (year / month / day as zero-padded strings).
        """
        ...

    def normalize_title(
        self,
        raw_title: str,
        mode: FaultMode,
    ) -> DmTitle:
        """Normalise a raw document title into a structured S1000D DmTitle.

        Applies casing rules, strips illegal characters, and splits
        into ``tech_name`` / ``info_name`` per S1000D conventions.
        The ``mode`` may influence the ``info_name`` suffix.
        """
        ...

    def default_language(self) -> Language:
        """Return the default language for DM header construction.

        Typically ``Language("en", "US")`` unless the deployment
        targets a different locale.
        """
        ...

    # ── B. Section & mode heuristics ──────────────────────────────
    # Purpose  : deterministic rules
    # Used by  : FaultSectionSelector, FaultModeRouter

    def fault_relevance_keywords(self) -> frozenset[str]:
        """Return keywords that indicate fault-relevant content.

        Used by the section selector for the deterministic first pass.
        Case-insensitive matching is the caller's responsibility.

        Examples: ``{"fault", "troubleshoot", "failure", "isolat",
        "repair", "lru", "sru"}``.
        """
        ...

    def fault_relevant_section_types(self) -> frozenset[str]:
        """Return section types that are inherently fault-relevant.

        These bypass keyword matching entirely — any section whose
        ``section_type`` is in this set is automatically included.

        Examples: ``{"fault_reporting", "fault_isolation",
        "troubleshooting"}``.
        """
        ...

    def assess_mode_by_structure(
        self,
        sections: list[Section],
    ) -> FaultMode | None:
        """Attempt to determine the fault mode from structural signals.

        Inspects section titles, section types, and keyword density
        to make a deterministic assessment.

        Returns
        -------
        FaultMode | None
            The mode if the heuristic is confident, or ``None`` if
            the signals are ambiguous and the LLM should be consulted.
        """
        ...

    # ── C. Table heuristics ───────────────────────────────────────
    # Purpose  : deterministic rules
    # Used by  : FaultTableClassifier

    def normalize_table_headers(
        self,
        headers: list[str],
    ) -> list[str]:
        """Normalise table column headers for rule-based classification.

        Applies lowercasing, whitespace collapsing, acronym expansion,
        and synonym mapping so that downstream header-pattern matching
        is resilient to surface-level variation.

        Preserves input order and length (1-to-1 with ``headers``).
        """
        ...

    def classify_table_by_headers(
        self,
        normalized_headers: list[str],
    ) -> TableType | None:
        """Classify a table's role from its normalised column headers.

        Returns
        -------
        TableType | None
            The ``TableType`` if the headers match a known pattern,
            or ``None`` if the headers are ambiguous and the LLM
            classifier should be consulted.
        """
        ...

    # ── D. Threshold / configuration lookup ───────────────────────
    # Purpose  : deterministic rules (configuration)
    # Used by  : FaultModeRouter, FaultTableClassifier,
    #            FaultSectionSelector

    def llm_confidence_threshold(self, task: str) -> float:
        """Return the minimum LLM confidence to accept for a given task.

        Parameters
        ----------
        task : str
            A free-form task key.  Well-known keys:
            ``"fault_relevance"``, ``"fault_mode"``,
            ``"table_classification"``, ``"fault_description"``,
            ``"isolation_steps"``, ``"lru_sru"``, ``"schematic"``.

        Returns
        -------
        float
            Threshold in ``[0.0, 1.0]``.  Implementations SHOULD
            return a sensible default (e.g. ``0.80``) for unknown keys.
        """
        ...

    # ── E. Fault-code derivation ──────────────────────────────────
    # Purpose  : deterministic rules
    # Used by  : FaultReportingMapper

    def derive_fault_code(
        self,
        fault_description: str,
        system_code: str,
    ) -> str:
        """Derive a deterministic fault code from a description and
        system code.

        The fault code is a schema-level identifier (not an LRU/SRU
        reference).  Derivation logic is deployment-specific — typical
        implementations hash or look up a mapping table.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════
#  3. MAPPING REVIEW POLICY PORT  (optional boundary hook)
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class MappingReviewPolicyPort(Protocol):
    """Optional policy port — determines whether a mapped module requires
    human review before being stored.

    Separates the review-policy decision from the mapping and validation
    logic.  Implementations may apply threshold-based rules, deployment-
    specific policies, or external approval workflows.

    If not injected, the assembler / use case defaults to
    ``ReviewStatus.NOT_REVIEWED`` (conservative — always requires
    human review).

    Contract
    --------
    • Single-method port — intentionally narrow.
    • The method is pure and deterministic given the trace.
    • The port MUST NOT mutate the trace or any other shared state.
    """

    # Purpose  : review / validation policy
    # Used by  : FaultModuleAssembler or FaultMappingUseCase (post-assembly)

    def determine_initial_review_status(
        self,
        trace: MappingTrace,
    ) -> ReviewStatus:
        """Determine the initial review status based on mapping provenance.

        Parameters
        ----------
        trace : MappingTrace
            The complete mapping trace produced by the assembler,
            containing per-field ``FieldOrigin`` records, unmapped
            sources, and warnings.

        Returns
        -------
        ReviewStatus
            Typical policy logic:
              • All ``FieldOrigin.confidence >= threshold`` and no
                warnings → ``ReviewStatus.APPROVED`` (auto-approve).
              • Any LLM-derived field below threshold or unmapped
                sources present → ``ReviewStatus.NOT_REVIEWED``.
              • Critical unmapped sources → ``ReviewStatus.IN_REVIEW``
                (flag for immediate attention).
        """
        ...


# ═══════════════════════════════════════════════════════════════════════
#  4. FAULT MODULE REPOSITORY PORT  (persistence boundary)
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class FaultModuleRepositoryPort(Protocol):
    """Port for durable storage of validated fault data modules.

    Implementations may target MongoDB, PostgreSQL, an in-memory store,
    or any other persistence backend.  The contract is expressed
    entirely in domain value objects (``PersistenceEnvelope``,
    ``PersistenceResult``).

    Contract
    --------
    • The ``collection`` field inside each ``PersistenceEnvelope``
      determines the logical target (e.g. ``"trusted"`` vs ``"review"``).
      Concrete adapters map this to their physical storage (collection,
      table, bucket, …).
    • ``save`` is upsert-by-``record_id`` — repeated saves for the
      same ``record_id`` within a collection replace the previous doc.
    • All methods are synchronous.
    """

    # ── Write ────────────────────────────────────────────────────

    def save(self, envelope: PersistenceEnvelope) -> PersistenceResult:
        """Persist a module envelope.

        Upserts: if a document with the same ``record_id`` already
        exists in the target collection, it is replaced.

        Parameters
        ----------
        envelope : PersistenceEnvelope
            Fully populated envelope including document, metadata,
            and target collection.

        Returns
        -------
        PersistenceResult
            ``success=True`` with ``stored_at`` timestamp on success,
            or ``success=False`` with ``error`` on failure.
        """
        ...

    # ── Read ─────────────────────────────────────────────────────

    def get(
        self,
        record_id: str,
        collection: str,
    ) -> PersistenceEnvelope | None:
        """Retrieve a previously persisted envelope by record ID.

        Parameters
        ----------
        record_id : str
            The module's ``record_id``.
        collection : str
            The logical collection to search (``"trusted"`` or
            ``"review"``).

        Returns
        -------
        PersistenceEnvelope | None
            The stored envelope, or ``None`` if not found.
        """
        ...

    def list_by_collection(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        """List envelopes in a collection with pagination.

        Parameters
        ----------
        collection : str
            The logical collection name.
        limit : int
            Maximum number of results.
        offset : int
            Number of results to skip.

        Returns
        -------
        list[PersistenceEnvelope]
            Envelopes ordered by ``stored_at`` descending.
        """
        ...

    def count(self, collection: str) -> int:
        """Count documents in a collection.

        Parameters
        ----------
        collection : str
            The logical collection name.

        Returns
        -------
        int
            Number of documents.
        """
        ...

    def list_record_ids(self, collection: str) -> list[str]:
        """Return all record IDs in a collection.

        Used by the reconciliation service to detect orphaned entries
        without loading full envelopes.

        Parameters
        ----------
        collection : str
            The logical collection name.

        Returns
        -------
        list[str]
            Record IDs (order is implementation-defined).
        """
        ...

    # ── Delete ───────────────────────────────────────────────────

    def delete(
        self,
        record_id: str,
        collection: str,
    ) -> PersistenceResult:
        """Remove a previously persisted envelope.

        Parameters
        ----------
        record_id : str
            The module's ``record_id``.
        collection : str
            The logical collection to delete from (``"trusted"``
            or ``"review"``).

        Returns
        -------
        PersistenceResult
            ``success=True`` if the document was deleted (or did
            not exist), or ``success=False`` on backend error.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════
#  5. TRUSTED MODULE HANDOFF PORT  (optional downstream hook)
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class TrustedModuleHandoffPort(Protocol):
    """Optional hook invoked after a module reaches the trusted collection.

    Implementations may trigger downstream indexing, event
    publication, notification, or any other side-effect that should
    occur once a module is promoted to trusted status.

    Contract
    --------
    • Single-method port — intentionally narrow.
    • Implementations MUST be idempotent — the same envelope may be
      handed off more than once (e.g. on retry).
    • Failures in the handoff MUST NOT roll back the promotion.
      The review service logs the error but the trusted write stands.
    """

    def on_module_stored(self, envelope: PersistenceEnvelope) -> None:
        """Called after a module is successfully stored in the trusted
        collection.

        Parameters
        ----------
        envelope : PersistenceEnvelope
            The envelope that was just persisted to trusted storage.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════
#  6. AUDIT REPOSITORY PORT  (review event logging)
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class AuditRepositoryPort(Protocol):
    """Port for durable storage of review audit events.

    Implementations may target a MongoDB collection, an in-memory list,
    or any other append-oriented storage.  The contract is expressed
    entirely in the domain ``AuditEntry`` value object.

    Contract
    --------
    • ``append`` is idempotent-safe — the same entry may be written
      more than once (implementations may deduplicate but are not
      required to).
    • ``list_by_record_id`` returns entries in chronological order
      (oldest first).
    • All methods are synchronous.
    """

    def append(self, entry: AuditEntry) -> None:
        """Persist a single audit entry.

        Parameters
        ----------
        entry : AuditEntry
            The audit event to record.

        Raises
        ------
        Exception
            On backend failure.  Callers decide whether to propagate
            or swallow.
        """
        ...

    def list_by_record_id(self, record_id: str) -> list[AuditEntry]:
        """Retrieve all audit entries for a given module.

        Parameters
        ----------
        record_id : str
            The fault module's ``record_id``.

        Returns
        -------
        list[AuditEntry]
            Entries in chronological order (oldest first).
            Empty list if none found.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════
#  7. METRICS SINK PORT  (observability)
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class MetricsSinkPort(Protocol):
    """Port for emitting lightweight operational metrics.

    Implementations may target StatsD, Prometheus, CloudWatch, an
    in-memory list (for testing), or ``/dev/null`` (no-op).

    The contract is intentionally minimal — three primitives cover
    counters, timings, and gauges.  Tags provide dimensionality.

    Contract
    --------
    • All methods are fire-and-forget.  Failures MUST be swallowed
      by implementations — metrics must never break business logic.
    • ``tags`` is a dict of string key-value pairs for dimensionality
      (e.g. ``{"collection": "trusted", "status": "success"}``).
    • All methods are synchronous.
    """

    def increment(
        self,
        name: str,
        value: int = 1,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter metric.

        Parameters
        ----------
        name : str
            Metric name (e.g. ``"persistence.save.success"``).
        value : int
            Amount to increment (default 1).
        tags : dict[str, str] | None
            Optional dimensional tags.
        """
        ...

    def timing(
        self,
        name: str,
        duration_ms: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Record a timing/duration metric.

        Parameters
        ----------
        name : str
            Metric name (e.g. ``"mapping.duration"``).
        duration_ms : float
            Duration in milliseconds.
        tags : dict[str, str] | None
            Optional dimensional tags.
        """
        ...

    def gauge(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge metric to a specific value.

        Parameters
        ----------
        name : str
            Metric name (e.g. ``"review.queue_depth"``).
        value : float
            The current value.
        tags : dict[str, str] | None
            Optional dimensional tags.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════
#  8. ASYNC FAULT MODULE REPOSITORY PORT
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class AsyncFaultModuleRepositoryPort(Protocol):
    """Async counterpart of ``FaultModuleRepositoryPort``.

    Same contract — every method is an ``async def`` coroutine.
    Implementations may use Motor (async MongoDB driver), an async
    in-memory store for testing, or an ``asyncio.to_thread`` bridge
    around a sync backend.
    """

    async def save(self, envelope: PersistenceEnvelope) -> PersistenceResult:
        ...

    async def get(
        self, record_id: str, collection: str,
    ) -> PersistenceEnvelope | None:
        ...

    async def list_by_collection(
        self, collection: str, *, limit: int = 100, offset: int = 0,
    ) -> list[PersistenceEnvelope]:
        ...

    async def count(self, collection: str) -> int:
        ...

    async def list_record_ids(self, collection: str) -> list[str]:
        ...

    async def delete(
        self, record_id: str, collection: str,
    ) -> PersistenceResult:
        ...


# ═══════════════════════════════════════════════════════════════════════
#  9. ASYNC AUDIT REPOSITORY PORT
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class AsyncAuditRepositoryPort(Protocol):
    """Async counterpart of ``AuditRepositoryPort``."""

    async def append(self, entry: AuditEntry) -> None:
        ...

    async def list_by_record_id(self, record_id: str) -> list[AuditEntry]:
        ...


# ═══════════════════════════════════════════════════════════════════════
#  10. ASYNC LLM INTERPRETER PORT
# ═══════════════════════════════════════════════════════════════════════


@runtime_checkable
class AsyncLlmInterpreterPort(Protocol):
    """Async counterpart of ``LlmInterpreterPort``.

    Real LLM calls are network-bound; async allows the event loop
    to serve other requests while waiting on the provider response.
    """

    async def assess_fault_relevance(
        self, section: Section,
    ) -> FaultRelevanceAssessment:
        ...

    async def interpret_fault_mode(
        self, sections: list[Section],
    ) -> FaultModeInterpretation:
        ...

    async def interpret_fault_descriptions(
        self, text: str, context: str,
    ) -> list[FaultDescriptionInterpretation]:
        ...

    async def interpret_isolation_steps(
        self, text: str, context: str,
    ) -> list[IsolationStepInterpretation]:
        ...

    async def classify_table(
        self, table: TableAsset,
    ) -> TableClassification:
        ...

    async def extract_lru_sru(
        self, text: str,
    ) -> list[LruSruExtraction]:
        ...

    async def correlate_schematic(
        self, schematic: SchematicsItem, fault_descriptions: list[str],
    ) -> SchematicCorrelation:
        ...
