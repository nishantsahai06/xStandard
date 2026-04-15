"""Unit tests for ``fault_mapper.application._shared_helpers``.

These are pure functions — no ports, no fakes needed.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.models import (
    CommonInfo,
    Lru,
    Section,
    Sru,
    TableAsset,
    TypedText,
)
from fault_mapper.domain.value_objects import LruSruExtraction

from fault_mapper.application._shared_helpers import (
    build_common_info,
    collect_pages,
    collect_tables,
    deduplicate_lru_sru,
    extraction_to_lru,
    extraction_to_sru,
    split_extractions,
    table_to_text,
)

from tests.conftest import make_chunk, make_section, make_table


# ═══════════════════════════════════════════════════════════════════════
#  build_common_info
# ═══════════════════════════════════════════════════════════════════════


class TestBuildCommonInfo:
    def test_returns_none_for_empty_sections(self):
        assert build_common_info([]) is None

    def test_single_section_populates_title_and_paragraphs(self):
        section = make_section(
            section_title="Intro",
            chunks=[make_chunk(chunk_text="Para 1", id="c1")],
        )
        result = build_common_info([section])
        assert result is not None
        assert result.title == "Intro"
        assert len(result.paragraphs) == 1
        assert result.paragraphs[0].text == "Para 1"
        assert result.paragraphs[0].source_chunk_id == "c1"

    def test_multiple_sections_use_first_title(self):
        s1 = make_section(section_title="First", id="s1")
        s2 = make_section(section_title="Second", id="s2")
        result = build_common_info([s1, s2])
        assert result is not None
        assert result.title == "First"

    def test_caps_paragraphs_at_max(self):
        chunks = [make_chunk(chunk_text=f"P{i}", id=f"c{i}") for i in range(25)]
        section = make_section(chunks=chunks)
        result = build_common_info([section])
        assert result is not None
        assert len(result.paragraphs) == 20  # _MAX_COMMON_INFO_PARAGRAPHS


# ═══════════════════════════════════════════════════════════════════════
#  collect_tables / collect_pages
# ═══════════════════════════════════════════════════════════════════════


class TestCollectTables:
    def test_empty_sections(self):
        assert collect_tables([]) == []

    def test_flattens_across_sections(self):
        t1 = make_table(id="t1")
        t2 = make_table(id="t2")
        s1 = make_section(tables=[t1])
        s2 = make_section(tables=[t2])
        result = collect_tables([s1, s2])
        assert [t.id for t in result] == ["t1", "t2"]


class TestCollectPages:
    def test_empty_sections(self):
        assert collect_pages([]) == []

    def test_flattens_page_numbers(self):
        s1 = make_section(page_numbers=[1, 2])
        s2 = make_section(page_numbers=[3])
        assert collect_pages([s1, s2]) == [1, 2, 3]


# ═══════════════════════════════════════════════════════════════════════
#  table_to_text
# ═══════════════════════════════════════════════════════════════════════


class TestTableToText:
    def test_prefers_markdown_summary(self):
        table = make_table(markdown_summary="| A | B |", caption="Cap")
        assert table_to_text(table) == "| A | B |"

    def test_fallback_to_caption_plus_headers_plus_rows(self):
        table = make_table(
            caption="Parts List",
            headers=["Part", "Qty"],
            rows=[["Bolt", "4"], ["Nut", "8"]],
            markdown_summary=None,
        )
        text = table_to_text(table)
        assert "Parts List" in text
        assert "Part | Qty" in text
        assert "Bolt | 4" in text

    def test_empty_table(self):
        table = make_table(
            caption=None, headers=[], rows=[], markdown_summary=None,
        )
        assert table_to_text(table) == ""


# ═══════════════════════════════════════════════════════════════════════
#  deduplicate_lru_sru
# ═══════════════════════════════════════════════════════════════════════


class TestDeduplicateLruSru:
    def test_removes_duplicates_by_name(self):
        items = [
            LruSruExtraction(name="Pump", is_lru=True, confidence=0.9),
            LruSruExtraction(name="pump", is_lru=True, confidence=0.8),
            LruSruExtraction(name="Valve", is_lru=False, confidence=0.7),
        ]
        result = deduplicate_lru_sru(items)
        names = [r.name for r in result]
        assert names == ["Pump", "Valve"]

    def test_preserves_items_with_empty_names(self):
        items = [
            LruSruExtraction(name="", is_lru=True, confidence=0.5),
            LruSruExtraction(name="", is_lru=False, confidence=0.6),
        ]
        result = deduplicate_lru_sru(items)
        assert len(result) == 2  # both kept

    def test_whitespace_only_names_kept(self):
        items = [
            LruSruExtraction(name="  ", is_lru=True, confidence=0.5),
            LruSruExtraction(name=" ", is_lru=True, confidence=0.4),
        ]
        result = deduplicate_lru_sru(items)
        assert len(result) == 2

    def test_empty_list(self):
        assert deduplicate_lru_sru([]) == []


# ═══════════════════════════════════════════════════════════════════════
#  extraction_to_lru / extraction_to_sru / split_extractions
# ═══════════════════════════════════════════════════════════════════════


class TestExtractionConverters:
    def test_extraction_to_lru(self):
        ext = LruSruExtraction(
            name="Pump", short_name="PMP", ident_number="29-10",
            is_lru=True, confidence=0.9,
        )
        lru = extraction_to_lru(ext)
        assert isinstance(lru, Lru)
        assert lru.name == "Pump"
        assert lru.short_name == "PMP"
        assert lru.ident_number == "29-10"

    def test_extraction_to_sru(self):
        ext = LruSruExtraction(
            name="Seal Kit", short_name="SK", ident_number="29-10-S",
            is_lru=False, confidence=0.8,
        )
        sru = extraction_to_sru(ext)
        assert isinstance(sru, Sru)
        assert sru.name == "Seal Kit"

    def test_split_extractions(self):
        items = [
            LruSruExtraction(name="LRU-A", is_lru=True, confidence=0.9),
            LruSruExtraction(name="SRU-B", is_lru=False, confidence=0.8),
            LruSruExtraction(name="LRU-C", is_lru=True, confidence=0.7),
        ]
        lrus, srus = split_extractions(items)
        assert len(lrus) == 2
        assert len(srus) == 1
        assert lrus[0].name == "LRU-A"
        assert srus[0].name == "SRU-B"

    def test_split_empty(self):
        lrus, srus = split_extractions([])
        assert lrus == []
        assert srus == []
