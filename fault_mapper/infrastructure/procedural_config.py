"""Procedural mapping configuration — all tuneable parameters.

Reuses ``LlmConfig`` and ``MongoConfig`` from the shared config.
Adds procedural-specific keyword sets, threshold overrides, and
title-normalisation rules.

Structure mirrors fault ``config.py``:
  ProceduralKeywordConfig    → procedural keyword sets & section types
  ProceduralThresholdConfig  → per-task LLM confidence thresholds
  ProceduralDmCodeDefaults   → info-code overrides for procedural DMs
  ProceduralTitleConfig      → title normalisation for procedural DMs
  ProceduralMappingConfig    → pipeline-wide procedural settings
  ProceduralAppConfig        → root aggregate (reuses LlmConfig, MongoConfig)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fault_mapper.infrastructure.config import LlmConfig, MongoConfig


# ═══════════════════════════════════════════════════════════════════════
#  PROCEDURAL KEYWORD / SECTION-TYPE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProceduralKeywordConfig:
    """Keywords and section-type allowlists for procedural filtering.

    Analogous to ``KeywordConfig`` but with procedural terms
    instead of fault terms.
    """

    procedural_relevance_keywords: frozenset[str] = frozenset(
        {
            "procedure",
            "task",
            "step",
            "instruction",
            "operation",
            "perform",
            "remove",
            "install",
            "inspect",
            "service",
            "maintenance",
            "check",
        },
    )

    procedural_relevant_section_types: frozenset[str] = frozenset(
        {
            "procedure",
            "task",
            "subtask",
            "maintenance",
            "servicing",
            "inspection",
            "removal",
            "installation",
        },
    )


# ═══════════════════════════════════════════════════════════════════════
#  PER-TASK LLM CONFIDENCE THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProceduralThresholdConfig:
    """Minimum LLM confidence for each procedural task.

    Mirrors ``ThresholdConfig`` with procedural-specific keys.
    """

    procedural_relevance: float = 0.80
    section_classification: float = 0.80
    step_extraction: float = 0.75
    requirement_extraction: float = 0.75
    reference_extraction: float = 0.70
    default: float = 0.80


# ═══════════════════════════════════════════════════════════════════════
#  DM-CODE DEFAULTS FOR PROCEDURAL DMS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProceduralDmCodeDefaults:
    """DM-code segment defaults for procedural data modules.

    Carries all base DM-code segments (shared with fault defaults)
    plus the procedural-specific info-code overrides.
    """

    # ── Base DM-code segments (fallbacks) ────────────────────────
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

    # ── S1000D info codes for procedural DM types ────────────────
    info_code_procedural: str = "200"     # Procedural DM
    info_code_descriptive: str = "040"    # Descriptive DM


# ═══════════════════════════════════════════════════════════════════════
#  PROCEDURAL TITLE NORMALISATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProceduralTitleConfig:
    """Title normalisation rules for procedural DMs."""

    max_tech_name_length: int = 256
    max_info_name_length: int = 256
    procedural_info_name: str = "Procedure"
    descriptive_info_name: str = "Description"
    strip_chars: str = "\t\n\r"
    collapse_whitespace: bool = True


# ═══════════════════════════════════════════════════════════════════════
#  PROCEDURAL MAPPING PIPELINE SETTINGS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProceduralMappingConfig:
    """Pipeline-wide procedural mapping configuration."""

    dm_code_defaults: ProceduralDmCodeDefaults = field(
        default_factory=ProceduralDmCodeDefaults,
    )
    thresholds: ProceduralThresholdConfig = field(
        default_factory=ProceduralThresholdConfig,
    )
    keywords: ProceduralKeywordConfig = field(
        default_factory=ProceduralKeywordConfig,
    )
    title: ProceduralTitleConfig = field(
        default_factory=ProceduralTitleConfig,
    )
    default_language_iso: str = "en"
    default_country_iso: str = "US"
    default_issue_number: str = "001"
    default_in_work: str = "00"
    mapping_version: str = "1.0.0"


# ═══════════════════════════════════════════════════════════════════════
#  ROOT PROCEDURAL CONFIG AGGREGATE
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProceduralAppConfig:
    """Root configuration for the procedural mapping pipeline.

    Reuses ``LlmConfig`` and ``MongoConfig`` from shared config —
    only ``mapping`` is procedural-specific.
    """

    llm: LlmConfig = field(default_factory=LlmConfig)
    mapping: ProceduralMappingConfig = field(
        default_factory=ProceduralMappingConfig,
    )
    mongo: MongoConfig = field(default_factory=MongoConfig)
