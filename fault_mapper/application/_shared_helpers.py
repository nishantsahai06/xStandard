"""Shared pure helpers for application-layer mappers.

These functions are stateless, port-free, and independently testable.
Extracted here to avoid duplication across ``FaultReportingMapper``
and ``FaultIsolationMapper``.
"""

from __future__ import annotations

from fault_mapper.domain.models import (
    CommonInfo,
    Lru,
    Section,
    Sru,
    TableAsset,
    TypedText,
)
from fault_mapper.domain.value_objects import LruSruExtraction

# ── Maximum paragraphs included in CommonInfo ────────────────────────
_MAX_COMMON_INFO_PARAGRAPHS = 20


def section_key(section: Section) -> str:
    """Stable key for a section (prefers ``id``, falls back to order).

    Shared across fault and procedural pipelines to ensure identical
    keying semantics when tracking per-section ``FieldOrigin`` provenance.
    """
    return section.id or f"section_{section.section_order}"


def build_common_info(sections: list[Section]) -> CommonInfo | None:
    """DIRECT: build ``CommonInfo`` from chunk text across sections.

    Returns ``None`` if there are no sections.  Caps paragraphs at
    ``_MAX_COMMON_INFO_PARAGRAPHS`` to keep the output practical.
    """
    if not sections:
        return None
    paragraphs = [
        TypedText(text=chunk.chunk_text, source_chunk_id=chunk.id)
        for section in sections
        for chunk in section.chunks
    ]
    return CommonInfo(
        title=sections[0].section_title,
        paragraphs=paragraphs[:_MAX_COMMON_INFO_PARAGRAPHS],
    )


def collect_tables(sections: list[Section]) -> list[TableAsset]:
    """Flatten tables from all sections into a single list."""
    return [t for s in sections for t in s.tables]


def collect_pages(sections: list[Section]) -> list[int]:
    """Flatten page numbers from all sections."""
    return [p for s in sections for p in s.page_numbers]


def table_to_text(table: TableAsset) -> str:
    """Serialise a table to plain text for LLM consumption."""
    if table.markdown_summary:
        return table.markdown_summary
    lines: list[str] = []
    if table.caption:
        lines.append(table.caption)
    if table.headers:
        lines.append(" | ".join(table.headers))
    for row in table.rows:
        lines.append(" | ".join(row))
    return "\n".join(lines)


def deduplicate_lru_sru(
    items: list[LruSruExtraction],
) -> list[LruSruExtraction]:
    """Remove duplicate LRU / SRU extractions by normalised name.

    Items with empty or whitespace-only names are kept as-is
    (never collapsed together) to avoid losing unrelated items.
    """
    seen: set[str] = set()
    unique: list[LruSruExtraction] = []
    for item in items:
        key = item.name.strip().lower()
        if not key:
            # Empty name — always keep (cannot meaningfully deduplicate)
            unique.append(item)
            continue
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def extraction_to_lru(extraction: LruSruExtraction) -> Lru:
    """Convert an ``LruSruExtraction`` VO into a canonical ``Lru``.

    Caller should ensure ``extraction.is_lru`` is ``True``.
    """
    return Lru(
        name=extraction.name,
        short_name=extraction.short_name,
        ident_number=extraction.ident_number,
    )


def extraction_to_sru(extraction: LruSruExtraction) -> Sru:
    """Convert an ``LruSruExtraction`` VO into a canonical ``Sru``.

    Caller should ensure ``extraction.is_lru`` is ``False``.
    """
    return Sru(
        name=extraction.name,
        short_name=extraction.short_name,
        ident_number=extraction.ident_number,
    )


def split_extractions(
    items: list[LruSruExtraction],
) -> tuple[list[LruSruExtraction], list[LruSruExtraction]]:
    """Split extractions into ``(lru_list, sru_list)`` by ``is_lru`` flag."""
    lrus = [e for e in items if e.is_lru]
    srus = [e for e in items if not e.is_lru]
    return lrus, srus
