"""Concrete rules-engine adapter — implements ``RulesEnginePort``.

All 14 methods are fully deterministic, reproducible, and auditable.
No LLM calls.  No randomness (except UUID generation which is by design).
No network I/O.  No database queries.

Config-driven: every tuneable parameter is read from ``MappingConfig``
which is injected at construction time.

Method groups
─────────────
A. Header defaults / DM-code assembly  (7 methods)
B. Section & mode heuristics            (3 methods)
C. Table heuristics                     (2 methods)
D. Threshold / configuration lookup     (1 method)
E. Fault-code derivation                (1 method)
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

from fault_mapper.domain.enums import FaultMode, TableType
from fault_mapper.domain.models import DocumentPipelineOutput, Section
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    IssueDate,
    IssueInfo,
    Language,
)
from fault_mapper.infrastructure.config import MappingConfig

from fault_mapper.adapters.secondary._adapter_helpers import (
    collapse_whitespace as _collapse_whitespace,
    safe_get as _safe_get,
)


# ─── helpers ─────────────────────────────────────────────────────────

_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9 ]")


# ═══════════════════════════════════════════════════════════════════════


class RulesAdapter:
    """Adapter that fulfils ``RulesEnginePort`` using deterministic rules.

    Every method reads from ``MappingConfig`` — no hard-coded magic
    values except where the S1000D spec mandates a fixed format (e.g.
    issue-number is always 3 digits).
    """

    def __init__(self, config: MappingConfig) -> None:
        self._cfg = config

    # ══════════════════════════════════════════════════════════════
    #  A.  Header defaults / DM-code assembly  (7 methods)
    # ══════════════════════════════════════════════════════════════

    def generate_record_id(self) -> str:
        """Generate a unique record identifier (UUID v4)."""
        return str(uuid.uuid4())

    def build_dm_code(
        self,
        source: DocumentPipelineOutput,
        mode: FaultMode,
    ) -> DmCode:
        """Construct the S1000D DM code from source metadata + mode.

        Strategy
        --------
        1. Try to extract ``model_ident_code`` and ``system_code``
           from ``source.metadata.upload_metadata`` / extraction_metadata.
        2. Fall back to ``DmCodeDefaults`` for every missing segment.
        3. ``info_code`` is derived from the fault mode.
        """
        dmc = self._cfg.dm_code_defaults
        up = source.metadata.upload_metadata if source.metadata else {}
        ex = source.metadata.extraction_metadata if source.metadata else {}

        model_ident = (
            _safe_get(up, "model_ident_code")
            or _safe_get(ex, "model_ident_code")
            or dmc.model_ident_code
        )
        system_code = (
            _safe_get(up, "system_code")
            or _safe_get(ex, "system_code")
            or dmc.system_code
        )

        info_code = self.determine_info_code(mode)

        return DmCode(
            model_ident_code=model_ident,
            system_diff_code=dmc.system_diff_code,
            system_code=system_code,
            sub_system_code=dmc.sub_system_code,
            sub_sub_system_code=dmc.sub_sub_system_code,
            assy_code=dmc.assy_code,
            disassy_code=dmc.disassy_code,
            disassy_code_variant=dmc.disassy_code_variant,
            info_code=info_code,
            info_code_variant=dmc.info_code_variant,
            item_location_code=dmc.item_location_code,
        )

    def determine_info_code(self, mode: FaultMode) -> str:
        """Return the 3-char infoCode for the given fault mode."""
        dmc = self._cfg.dm_code_defaults
        if mode is FaultMode.FAULT_REPORTING:
            return dmc.info_code_reporting
        return dmc.info_code_isolation

    def resolve_issue_info(self) -> IssueInfo:
        """Return the configured issue number and in-work indicator."""
        return IssueInfo(
            issue_number=self._cfg.default_issue_number,
            in_work=self._cfg.default_in_work,
        )

    def resolve_issue_date(self) -> IssueDate:
        """Return today's date formatted per S1000D convention."""
        today = datetime.now(timezone.utc).date()
        return IssueDate(
            year=f"{today.year:04d}",
            month=f"{today.month:02d}",
            day=f"{today.day:02d}",
        )

    def normalize_title(
        self,
        raw_title: str,
        mode: FaultMode,
    ) -> DmTitle:
        """Normalise a raw document title into a structured DmTitle.

        Steps
        -----
        1. Strip control characters.
        2. Collapse whitespace.
        3. Truncate ``tech_name`` to max length.
        4. Assign ``info_name`` based on the resolved fault mode.
        """
        tc = self._cfg.title
        cleaned = raw_title
        for ch in tc.strip_chars:
            cleaned = cleaned.replace(ch, " ")
        if tc.collapse_whitespace:
            cleaned = _collapse_whitespace(cleaned)
        # Remove truly illegal chars but keep basic punctuation
        cleaned = cleaned.strip()

        tech_name = cleaned[: tc.max_tech_name_length] if cleaned else "Untitled"

        if mode is FaultMode.FAULT_REPORTING:
            info_name = tc.reporting_info_name
        else:
            info_name = tc.isolation_info_name

        return DmTitle(
            tech_name=tech_name,
            info_name=info_name,
        )

    def default_language(self) -> Language:
        """Return the default language for DM header construction."""
        return Language(
            language_iso_code=self._cfg.default_language_iso,
            country_iso_code=self._cfg.default_country_iso,
        )

    # ══════════════════════════════════════════════════════════════
    #  B.  Section & mode heuristics  (3 methods)
    # ══════════════════════════════════════════════════════════════

    def fault_relevance_keywords(self) -> frozenset[str]:
        """Return keywords that indicate fault-relevant content."""
        return self._cfg.keywords.fault_relevance_keywords

    def fault_relevant_section_types(self) -> frozenset[str]:
        """Return section types that are inherently fault-relevant."""
        return self._cfg.keywords.fault_relevant_section_types

    def assess_mode_by_structure(
        self,
        sections: list[Section],
    ) -> FaultMode | None:
        """Attempt to determine the fault mode from structural signals.

        Algorithm
        ---------
        1. Count matches of ``reporting_keywords`` vs ``isolation_keywords``
           across all section titles and section_type values.
        2. If one side has ≥ 2× the score of the other → return that mode.
        3. Otherwise → return ``None`` (ambiguous, defer to LLM).
        """
        reporting_kws = self._cfg.keywords.reporting_keywords
        isolation_kws = self._cfg.keywords.isolation_keywords

        reporting_score = 0
        isolation_score = 0

        for section in sections:
            text_lower = (
                (section.section_title or "")
                + " "
                + (section.section_type or "")
            ).lower()
            for kw in reporting_kws:
                if kw in text_lower:
                    reporting_score += 1
            for kw in isolation_kws:
                if kw in text_lower:
                    isolation_score += 1

        if reporting_score == 0 and isolation_score == 0:
            return None
        if reporting_score >= 2 * max(isolation_score, 1):
            return FaultMode.FAULT_REPORTING
        if isolation_score >= 2 * max(reporting_score, 1):
            return FaultMode.FAULT_ISOLATION
        return None

    # ══════════════════════════════════════════════════════════════
    #  C.  Table heuristics  (2 methods)
    # ══════════════════════════════════════════════════════════════

    def normalize_table_headers(
        self,
        headers: list[str],
    ) -> list[str]:
        """Normalise table column headers for rule-based classification.

        Steps
        -----
        1. Lowercase.
        2. Collapse whitespace.
        3. Map synonyms via ``TableHeaderConfig.header_synonyms``.
        """
        synonyms = self._cfg.table_headers.header_synonyms
        result: list[str] = []
        for h in headers:
            normalised = _collapse_whitespace(h.lower())
            # Try exact match first, then see if it's a known synonym
            canonical = synonyms.get(normalised, normalised)
            result.append(canonical)
        return result

    def classify_table_by_headers(
        self,
        normalized_headers: list[str],
    ) -> TableType | None:
        """Classify a table's role from its normalised column headers.

        For each pattern in ``TableHeaderConfig.header_patterns``,
        check whether ALL tokens in the pattern frozenset appear in
        the header list.  Return the first match.  Return ``None``
        if no pattern matches (LLM fallback needed).
        """
        header_set = set(normalized_headers)
        for pattern_tokens, table_type_value in self._cfg.table_headers.header_patterns.items():
            if pattern_tokens.issubset(header_set):
                return TableType(table_type_value)
        return None

    # ══════════════════════════════════════════════════════════════
    #  D.  Threshold / configuration lookup  (1 method)
    # ══════════════════════════════════════════════════════════════

    def llm_confidence_threshold(self, task: str) -> float:
        """Return the minimum LLM confidence to accept for a task.

        Maps well-known task keys to ``ThresholdConfig`` fields.
        Unknown keys fall back to ``ThresholdConfig.default``.
        """
        tc = self._cfg.thresholds
        lookup: dict[str, float] = {
            "fault_relevance": tc.fault_relevance,
            "fault_mode": tc.fault_mode,
            "table_classification": tc.table_classification,
            "fault_description": tc.fault_description,
            "isolation_steps": tc.isolation_steps,
            "lru_sru": tc.lru_sru,
            "schematic": tc.schematic,
        }
        return lookup.get(task, tc.default)

    # ══════════════════════════════════════════════════════════════
    #  E.  Fault-code derivation  (1 method)
    # ══════════════════════════════════════════════════════════════

    def derive_fault_code(
        self,
        fault_description: str,
        system_code: str,
    ) -> str:
        """Derive a deterministic fault code from description + system code.

        Algorithm: SHA-256 of the concatenation, truncated to 8 hex chars,
        prefixed with the system code.  This gives a stable, reproducible
        identifier for each unique (description, system) pair.
        """
        digest = hashlib.sha256(
            f"{system_code}:{fault_description}".encode(),
        ).hexdigest()[:8]
        return f"{system_code}-{digest}".upper()
