"""Mapper configuration — all tuneable parameters in one place.

Loaded once at application startup by the infrastructure factory.
Passed by value into adapters/services that need it.

No service should read environment variables directly — all external
config must flow through these dataclasses.

Structure
─────────
  LlmConfig           → LLM provider / model / generation settings
  DmCodeDefaults      → DM-code segment fallback values
  ThresholdConfig     → per-task LLM confidence thresholds
  KeywordConfig       → keyword sets, section-type allowlists
  TableHeaderConfig   → synonym maps, header→TableType patterns
  TitleConfig         → title normalisation rules
  MappingConfig       → pipeline-wide settings (version, defaults)
  AppConfig           → root aggregate (llm + mapping)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════
#  LLM PROVIDER SETTINGS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LlmConfig:
    """Configuration for the LLM adapter.

    ``provider`` selects the SDK / HTTP shape.
    ``api_key`` may be ``None`` when the provider is ``"local"`` or
    the key is sourced from the environment at adapter construction.
    """

    provider: str = "openai"            # "openai" | "anthropic" | "local"
    model: str = "gpt-4o"
    temperature: float = 0.0            # deterministic by default
    max_tokens: int = 4096
    timeout_seconds: int = 60
    api_key: str | None = None          # None → read from env


# ═══════════════════════════════════════════════════════════════════════
#  DM-CODE SEGMENT DEFAULTS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DmCodeDefaults:
    """Fallback values for DM-code segments when source metadata is
    absent or incomplete."""

    model_ident_code: str = "UNKNOWN"
    system_diff_code: str = "A"
    system_code: str = "00"
    sub_system_code: str = "00"
    sub_sub_system_code: str = "00"
    assy_code: str = "00"
    disassy_code: str = "00"
    disassy_code_variant: str = "A"
    info_code_variant: str = "A"
    item_location_code: str = "A"

    # info-code look-up  (mode → 3-char code)
    info_code_reporting: str = "031"
    info_code_isolation: str = "032"


# ═══════════════════════════════════════════════════════════════════════
#  PER-TASK LLM CONFIDENCE THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ThresholdConfig:
    """Minimum LLM confidence to accept for each well-known task.

    Unknown task keys fall back to ``default``.
    """

    fault_relevance: float = 0.80
    fault_mode: float = 0.85
    table_classification: float = 0.80
    fault_description: float = 0.75
    isolation_steps: float = 0.75
    lru_sru: float = 0.75
    schematic: float = 0.70
    default: float = 0.80


# ═══════════════════════════════════════════════════════════════════════
#  KEYWORD / SECTION-TYPE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class KeywordConfig:
    """Keywords and section-type allowlists for deterministic filtering."""

    fault_relevance_keywords: frozenset[str] = frozenset(
        {
            "fault",
            "troubleshoot",
            "failure",
            "isolat",
            "repair",
            "lru",
            "sru",
            "defect",
            "malfunction",
            "diagnostic",
        },
    )

    fault_relevant_section_types: frozenset[str] = frozenset(
        {
            "fault_reporting",
            "fault_isolation",
            "troubleshooting",
        },
    )

    # ── Mode-detection keyword groups ────────────────────────────
    reporting_keywords: frozenset[str] = frozenset(
        {
            "fault reporting",
            "detected fault",
            "fault code",
            "fault entry",
            "fault description",
            "observed fault",
        },
    )
    isolation_keywords: frozenset[str] = frozenset(
        {
            "fault isolation",
            "troubleshoot",
            "isolation step",
            "diagnostic",
            "yes/no",
            "decision tree",
        },
    )


# ═══════════════════════════════════════════════════════════════════════
#  TABLE HEADER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TableHeaderConfig:
    """Synonym maps and header-pattern → TableType rules.

    ``header_synonyms`` collapses surface variation before pattern
    matching.  ``header_patterns`` maps a frozenset of normalised
    header tokens to a ``TableType`` string value.
    """

    # lower-cased synonym → canonical form
    header_synonyms: dict[str, str] = field(default_factory=lambda: {
        "part number": "part_number",
        "part no": "part_number",
        "part no.": "part_number",
        "p/n": "part_number",
        "nomenclature": "name",
        "description": "name",
        "item": "name",
        "qty": "quantity",
        "quantity": "quantity",
        "lru": "lru",
        "line replaceable unit": "lru",
        "sru": "sru",
        "shop replaceable unit": "sru",
        "nsn": "nsn",
        "national stock number": "nsn",
        "cage": "cage_code",
        "cage code": "cage_code",
        "fault code": "fault_code",
        "fault message": "fault_message",
        "equipment": "equipment",
        "support equipment": "support_equipment",
        "tool": "support_equipment",
        "supply": "supply",
        "consumable": "supply",
        "spare": "spare",
    })

    # canonical header-set → TableType.value
    # Each key is a frozenset of canonical tokens that MUST ALL
    # appear in the normalised header row for a match.
    header_patterns: dict[frozenset[str], str] = field(
        default_factory=lambda: {
            frozenset({"lru", "part_number"}): "lru_list",
            frozenset({"lru", "name"}): "lru_list",
            frozenset({"sru", "part_number"}): "sru_list",
            frozenset({"sru", "name"}): "sru_list",
            frozenset({"spare", "part_number"}): "spares",
            frozenset({"support_equipment"}): "support_equipment",
            frozenset({"supply"}): "supplies",
            frozenset({"fault_code", "fault_message"}): "fault_code_table",
            frozenset({"fault_code", "name"}): "fault_code_table",
        },
    )


# ═══════════════════════════════════════════════════════════════════════
#  TITLE NORMALISATION CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TitleConfig:
    """Rules for normalising raw document titles into DmTitle."""

    max_tech_name_length: int = 256
    max_info_name_length: int = 256
    reporting_info_name: str = "Fault Reporting"
    isolation_info_name: str = "Fault Isolation"
    strip_chars: str = "\t\n\r"
    collapse_whitespace: bool = True


# ═══════════════════════════════════════════════════════════════════════
#  MAPPING PIPELINE SETTINGS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MappingConfig:
    """Pipeline-wide mapping configuration."""

    # ── Header / DM-code defaults ────────────────────────────────
    dm_code_defaults: DmCodeDefaults = field(
        default_factory=DmCodeDefaults,
    )

    # ── Language defaults ────────────────────────────────────────
    default_language_iso: str = "en"
    default_country_iso: str = "US"
    default_issue_number: str = "001"
    default_in_work: str = "00"

    # ── Thresholds ───────────────────────────────────────────────
    thresholds: ThresholdConfig = field(
        default_factory=ThresholdConfig,
    )

    # ── Keywords & section types ─────────────────────────────────
    keywords: KeywordConfig = field(
        default_factory=KeywordConfig,
    )

    # ── Table header rules ───────────────────────────────────────
    table_headers: TableHeaderConfig = field(
        default_factory=TableHeaderConfig,
    )

    # ── Title normalisation ──────────────────────────────────────
    title: TitleConfig = field(
        default_factory=TitleConfig,
    )

    # ── Version stamp ────────────────────────────────────────────
    mapping_version: str = "1.0.0"


# ═══════════════════════════════════════════════════════════════════════
#  ROOT CONFIG AGGREGATE
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MongoConfig:
    """Configuration for the MongoDB persistence adapter.

    ``connection_uri`` is the full MongoDB connection string.
    ``database_name`` is the target database.
    ``trusted_collection`` and ``review_collection`` are the logical
    collection names used by the persistence service.
    ``audit_collection`` stores review audit events.
    """

    connection_uri: str = "mongodb://localhost:27017"
    database_name: str = "fault_mapper"
    trusted_collection: str = "fault_modules_trusted"
    review_collection: str = "fault_modules_review"
    audit_collection: str = "fault_modules_audit"


@dataclass(frozen=True)
class AppConfig:
    """Root configuration aggregate.

    Created once at startup and passed into the infrastructure factory.
    """

    llm: LlmConfig = field(default_factory=LlmConfig)
    mapping: MappingConfig = field(default_factory=MappingConfig)
    mongo: MongoConfig = field(default_factory=MongoConfig)
