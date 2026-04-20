"""Procedural requirement extractor — extracts preliminary requirements.

Scans source sections for requirement-like content:
  Pass 1 (RULE/DIRECT): tables with equipment/supply/safety headers.
  Pass 2 (LLM): requirement prose in body text.

Returns a flat list of ``ProceduralRequirementItem`` — the assembler
places these into ``content.preliminaryRequirements[]``.
"""

from __future__ import annotations

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.models import Section
from fault_mapper.domain.procedural_models import ProceduralRequirementItem
from fault_mapper.domain.procedural_ports import (
    ProceduralLlmInterpreterPort,
    ProceduralRulesEnginePort,
)
from fault_mapper.domain.procedural_value_objects import (
    RequirementInterpretation,
)
from fault_mapper.domain.value_objects import FieldOrigin

from fault_mapper.application._shared_helpers import section_key


_REQUIREMENT_TABLE_KEYWORDS = frozenset({
    "equipment", "tool", "supply", "consumable",
    "spare", "part number", "personnel", "safety",
})


class ProceduralRequirementExtractor:
    """Extracts preliminary requirements from source sections.

    Pipeline:
      1. Scan tables for requirement-like headers → deterministic.
      2. LLM interprets requirement prose → confidence-gated.
      3. Merge and deduplicate.
    """

    def __init__(
        self,
        rules: ProceduralRulesEnginePort,
        llm: ProceduralLlmInterpreterPort,
    ) -> None:
        self._rules = rules
        self._llm = llm

    # ── Public API ───────────────────────────────────────────────

    def extract(
        self,
        sections: list[Section],
        existing_origins: dict[str, FieldOrigin],
    ) -> tuple[list[ProceduralRequirementItem], dict[str, FieldOrigin]]:
        """Extract preliminary requirements from source sections.

        Returns a flat list of requirement items + origins.
        """
        threshold = self._rules.llm_confidence_threshold(
            "requirement_extraction",
        )

        items: list[ProceduralRequirementItem] = []
        origins: dict[str, FieldOrigin] = {}

        for section in sections:
            # Pass 1: deterministic table extraction
            table_items, table_origins = self._extract_from_tables(section)
            items.extend(table_items)
            origins.update(table_origins)

            # Pass 2: LLM extraction from prose
            llm_items, llm_origins = self._extract_from_prose(
                section, threshold,
            )
            items.extend(llm_items)
            origins.update(llm_origins)

        # Deduplicate by (requirement_type, name, ident_number)
        items = _deduplicate(items)

        return items, origins

    # ── Internals ────────────────────────────────────────────────

    def _extract_from_tables(
        self,
        section: Section,
    ) -> tuple[list[ProceduralRequirementItem], dict[str, FieldOrigin]]:
        """Deterministic extraction from tables with requirement headers."""
        items: list[ProceduralRequirementItem] = []
        origins: dict[str, FieldOrigin] = {}

        for table in section.tables:
            headers_lower = [h.lower() for h in table.headers]
            joined_headers = " ".join(headers_lower)
            if not any(kw in joined_headers for kw in _REQUIREMENT_TABLE_KEYWORDS):
                continue

            req_type = _infer_requirement_type(headers_lower)

            for row_idx, row in enumerate(table.rows):
                item = _row_to_requirement(
                    req_type, table.headers, row, table.id,
                )
                if item is not None:
                    items.append(item)
                    key = (
                        f"req.table.{table.id or 'unknown'}"
                        f".row_{row_idx}"
                    )
                    origins[key] = FieldOrigin(
                        strategy=MappingStrategy.DIRECT,
                        source_path=(
                            f"sections[{section.section_order}]"
                            f".tables[{table.id or '?'}]"
                            f".rows[{row_idx}]"
                        ),
                        confidence=1.0,
                        source_chunk_id=table.id,
                    )

        return items, origins

    def _extract_from_prose(
        self,
        section: Section,
        threshold: float,
    ) -> tuple[list[ProceduralRequirementItem], dict[str, FieldOrigin]]:
        """LLM extraction of requirements from prose text."""
        items: list[ProceduralRequirementItem] = []
        origins: dict[str, FieldOrigin] = {}

        interpretations = self._llm.interpret_requirements(
            section.section_text,
            context=section.section_title,
        )

        for idx, interp in enumerate(interpretations):
            if interp.confidence < threshold:
                continue

            item = _interpretation_to_item(interp)
            items.append(item)

            key = f"req.llm.{section_key(section)}.{idx}"
            origins[key] = FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path=(
                    f"sections[{section.section_order}].section_text"
                ),
                confidence=interp.confidence,
                source_chunk_id=section.id,
            )

        return items, origins


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _infer_requirement_type(headers_lower: list[str]) -> str:
    """Infer requirement type from table headers."""
    joined = " ".join(headers_lower)
    if "personnel" in joined or "role" in joined or "skill" in joined:
        return "personnel"
    if "spare" in joined:
        return "spare"
    if "supply" in joined or "consumable" in joined:
        return "supply"
    if "safety" in joined or "hazard" in joined:
        return "safety"
    return "equipment"


def _row_to_requirement(
    req_type: str,
    headers: list[str],
    row: list[str],
    table_id: str | None,
) -> ProceduralRequirementItem | None:
    """Convert one table row to a requirement item."""
    if not row or all(not cell.strip() for cell in row):
        return None

    # Build a header→value map
    values: dict[str, str] = {
        h.lower(): row[i] if i < len(row) else ""
        for i, h in enumerate(headers)
    }

    return ProceduralRequirementItem(
        requirement_type=req_type,
        name=_first_value(
            values, ["name", "nomenclature", "description", "item", "tool", "equipment"],
        ),
        ident_number=_first_value(
            values, ["part number", "part no", "p/n", "nsn", "ident"],
        ),
        quantity=_parse_qty(_first_value(values, ["qty", "quantity"]) or "0"),
        unit=_first_value(values, ["unit", "uom"]),
        role=_first_value(values, ["role"]),
        skill_level=_first_value(values, ["skill", "skill level"]),
        safety_text=_first_value(values, ["safety", "hazard", "warning"]),
        source_table_id=table_id,
    )


def _first_value(values: dict[str, str], keys: list[str]) -> str | None:
    """Return the first non-empty value matching any of the given keys."""
    for key in keys:
        for header, val in values.items():
            if key in header and val.strip():
                return val.strip()
    return None


def _parse_qty(text: str) -> float:
    """Parse a quantity string, defaulting to 0."""
    try:
        return float(text.strip())
    except (ValueError, TypeError):
        return 0.0


def _interpretation_to_item(
    interp: RequirementInterpretation,
) -> ProceduralRequirementItem:
    """Convert an LLM interpretation to a requirement item."""
    return ProceduralRequirementItem(
        requirement_type=interp.requirement_type,
        name=interp.name,
        ident_number=interp.ident_number,
        quantity=interp.quantity,
        unit=interp.unit,
        role=interp.role,
        skill_level=interp.skill_level,
        safety_text=interp.safety_text,
    )


def _deduplicate(
    items: list[ProceduralRequirementItem],
) -> list[ProceduralRequirementItem]:
    """Remove duplicate requirements by (type, name, ident_number)."""
    seen: set[tuple[str, str | None, str | None]] = set()
    unique: list[ProceduralRequirementItem] = []
    for item in items:
        key = (item.requirement_type, item.name, item.ident_number)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
