"""Concrete procedural rules-engine adapter — implements ``ProceduralRulesEnginePort``.

All 12 methods are fully deterministic, reproducible, and auditable.
No LLM calls.  No randomness (except UUID generation which is by design).
No network I/O.  No database queries.

Config-driven: every tuneable parameter is read from ``ProceduralMappingConfig``
which is injected at construction time.

Method groups
─────────────
A. Header defaults / DM-code assembly  (7 methods)
B. Procedural heuristics               (3 methods)
C. Step normalisation                   (1 method)
D. Threshold / configuration lookup     (1 method)
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fault_mapper.domain.models import DocumentPipelineOutput, Section
from fault_mapper.domain.procedural_enums import (
    ProceduralModuleType,
    ProceduralSectionType,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    IssueDate,
    IssueInfo,
    Language,
)
from fault_mapper.infrastructure.procedural_config import (
    ProceduralMappingConfig,
)

from fault_mapper.adapters.secondary._adapter_helpers import (
    collapse_whitespace as _collapse_whitespace,
    safe_get as _safe_get,
)


# ─── helpers ─────────────────────────────────────────────────────────

_STEP_PREFIX_RE = re.compile(
    r"^(?:step\s*)?(\d+)([a-zA-Z])?(?:\.\s*)?$|"
    r"^(\d+)\.(\d+[a-zA-Z]?)$|"
    r"^([a-zA-Z])\.?$",
    re.IGNORECASE,
)

# ── Section-type heuristics mapping ──────────────────────────────────
_SECTION_TYPE_KEYWORDS: dict[str, ProceduralSectionType] = {
    "removal": ProceduralSectionType.REMOVAL,
    "remove": ProceduralSectionType.REMOVAL,
    "installation": ProceduralSectionType.INSTALLATION,
    "install": ProceduralSectionType.INSTALLATION,
    "inspection": ProceduralSectionType.INSPECTION,
    "inspect": ProceduralSectionType.INSPECTION,
    "test": ProceduralSectionType.TEST,
    "testing": ProceduralSectionType.TEST,
    "servicing": ProceduralSectionType.SERVICING,
    "service": ProceduralSectionType.SERVICING,
    "cleaning": ProceduralSectionType.CLEANING,
    "clean": ProceduralSectionType.CLEANING,
    "adjustment": ProceduralSectionType.ADJUSTMENT,
    "adjust": ProceduralSectionType.ADJUSTMENT,
    "setup": ProceduralSectionType.SETUP,
    "preparation": ProceduralSectionType.SETUP,
    "procedure": ProceduralSectionType.PROCEDURE,
}


# ═══════════════════════════════════════════════════════════════════════


class ProceduralRulesAdapter:
    """Adapter that fulfils ``ProceduralRulesEnginePort`` using deterministic rules.

    Every method reads from ``ProceduralMappingConfig`` — no hard-coded
    magic values except where the S1000D spec mandates a fixed format.
    """

    def __init__(self, config: ProceduralMappingConfig) -> None:
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
        module_type: ProceduralModuleType,
    ) -> DmCode:
        """Construct the S1000D DM code from source metadata + module type.

        Strategy
        --------
        1. Try to extract ``model_ident_code`` and ``system_code``
           from ``source.metadata.upload_metadata`` / extraction_metadata.
        2. Fall back to ``ProceduralDmCodeDefaults`` for every missing segment.
        3. ``info_code`` is derived from the module type.
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

        info_code = self.determine_info_code(module_type)

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

    def determine_info_code(
        self,
        module_type: ProceduralModuleType,
    ) -> str:
        """Return the 3-char infoCode for the given module type."""
        dmc = self._cfg.dm_code_defaults
        if module_type is ProceduralModuleType.PROCEDURAL:
            return dmc.info_code_procedural
        return dmc.info_code_descriptive

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
        module_type: ProceduralModuleType,
    ) -> DmTitle:
        """Normalise a raw document title into a structured DmTitle.

        Steps
        -----
        1. Strip control characters.
        2. Collapse whitespace.
        3. Truncate ``tech_name`` to max length.
        4. Assign ``info_name`` based on the module type.
        """
        tc = self._cfg.title
        cleaned = raw_title
        for ch in tc.strip_chars:
            cleaned = cleaned.replace(ch, " ")
        if tc.collapse_whitespace:
            cleaned = _collapse_whitespace(cleaned)
        cleaned = cleaned.strip()

        tech_name = (
            cleaned[: tc.max_tech_name_length] if cleaned else "Untitled"
        )

        if module_type is ProceduralModuleType.PROCEDURAL:
            info_name = tc.procedural_info_name
        else:
            info_name = tc.descriptive_info_name

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
    #  B.  Procedural heuristics  (3 methods)
    # ══════════════════════════════════════════════════════════════

    def procedural_relevance_keywords(self) -> frozenset[str]:
        """Return keywords that indicate procedural content."""
        return self._cfg.keywords.procedural_relevance_keywords

    def procedural_relevant_section_types(self) -> frozenset[str]:
        """Return section types that are inherently procedural."""
        return self._cfg.keywords.procedural_relevant_section_types

    def classify_section_by_structure(
        self,
        section: Section,
    ) -> ProceduralSectionType | None:
        """Attempt rule-based section classification from title and type.

        Algorithm
        ---------
        1. Check section_type against known procedural section types.
        2. Scan section_title for keyword matches.
        3. Return ``None`` if inconclusive (LLM fallback needed).
        """
        # Check section_type directly
        try:
            return ProceduralSectionType(section.section_type.lower())
        except ValueError:
            pass

        # Scan title for classification keywords
        title_lower = (section.section_title or "").lower()
        for keyword, section_type in _SECTION_TYPE_KEYWORDS.items():
            if keyword in title_lower:
                return section_type

        return None

    # ══════════════════════════════════════════════════════════════
    #  C.  Step normalisation  (1 method)
    # ══════════════════════════════════════════════════════════════

    def normalize_step_number(self, raw_number: str) -> str:
        """Normalise "Step 1", "1.", "1)", "a." → canonical form.

        Canonical forms:
          "Step 1"  → "1"
          "1."      → "1"
          "1a"      → "1.a"
          "a."      → "a"
          "2.1"     → "2.1"
        """
        cleaned = raw_number.strip().rstrip(".)")
        # Strip "Step " prefix
        if cleaned.lower().startswith("step"):
            cleaned = cleaned[4:].strip()
        # Already in "N.M" form
        if re.match(r"^\d+\.\d+[a-zA-Z]?$", cleaned):
            return cleaned
        # "1a" → "1.a"
        m = re.match(r"^(\d+)([a-zA-Z])$", cleaned)
        if m:
            return f"{m.group(1)}.{m.group(2)}"
        return cleaned

    # ══════════════════════════════════════════════════════════════
    #  D.  Threshold / configuration lookup  (1 method)
    # ══════════════════════════════════════════════════════════════

    def llm_confidence_threshold(self, task: str) -> float:
        """Return the minimum LLM confidence to accept for a task.

        Maps well-known task keys to ``ProceduralThresholdConfig`` fields.
        Unknown keys fall back to ``ProceduralThresholdConfig.default``.
        """
        tc = self._cfg.thresholds
        lookup: dict[str, float] = {
            "procedural_relevance": tc.procedural_relevance,
            "section_classification": tc.section_classification,
            "step_extraction": tc.step_extraction,
            "requirement_extraction": tc.requirement_extraction,
            "reference_extraction": tc.reference_extraction,
        }
        return lookup.get(task, tc.default)
