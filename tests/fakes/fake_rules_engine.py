"""Fake rules engine — in-memory test double for ``RulesEnginePort``.

All 14 methods are implemented with sensible defaults.  Every attribute
is public and mutable so tests can override canned values per-scenario.

Call tracking is included: ``calls[method_name]`` holds a list of
argument tuples for every invocation.
"""

from __future__ import annotations

import uuid
from typing import Any

from fault_mapper.domain.enums import FaultMode, TableType
from fault_mapper.domain.models import DocumentPipelineOutput, Section
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    IssueDate,
    IssueInfo,
    Language,
)


class FakeRulesEngine:
    """Configurable fake implementing ``RulesEnginePort`` (14 methods)."""

    def __init__(self) -> None:
        # ── Canned return values ─────────────────────────────────
        self.record_id_value: str = "rec-test-001"
        self.dm_code_value = DmCode(
            model_ident_code="TESTAC",
            system_diff_code="A",
            system_code="29",
            sub_system_code="00",
            sub_sub_system_code="00",
            assy_code="00",
            disassy_code="A",
            disassy_code_variant="A",
            info_code="031",
            info_code_variant="A",
            item_location_code="A",
        )
        self.info_code_value: str = "031"
        self.issue_info_value = IssueInfo(issue_number="001", in_work="00")
        self.issue_date_value = IssueDate(year="2026", month="04", day="13")
        self.title_value = DmTitle(
            tech_name="Fault Report",
            info_name="Fault Reporting",
        )
        self.language_value = Language(
            language_iso_code="en",
            country_iso_code="US",
        )
        self.keywords_value: frozenset[str] = frozenset(
            {"fault", "troubleshoot", "failure", "isolat", "repair", "lru", "sru"},
        )
        self.section_types_value: frozenset[str] = frozenset(
            {"fault_reporting", "fault_isolation", "troubleshooting"},
        )
        self.mode_by_structure_value: FaultMode | None = None  # inconclusive
        self.normalized_headers_value: list[str] | None = None  # use input
        self.table_by_headers_value: TableType | None = None  # inconclusive
        self.threshold_value: float = 0.80
        self.fault_code_value: str = "FC-RULE-001"

        # ── Call tracker ─────────────────────────────────────────
        self.calls: dict[str, list[Any]] = {
            "generate_record_id": [],
            "build_dm_code": [],
            "determine_info_code": [],
            "resolve_issue_info": [],
            "resolve_issue_date": [],
            "normalize_title": [],
            "default_language": [],
            "fault_relevance_keywords": [],
            "fault_relevant_section_types": [],
            "assess_mode_by_structure": [],
            "normalize_table_headers": [],
            "classify_table_by_headers": [],
            "llm_confidence_threshold": [],
            "derive_fault_code": [],
        }

    # ── A. Header defaults / DM-code assembly (7 methods) ────────

    def generate_record_id(self) -> str:
        self.calls["generate_record_id"].append(())
        return self.record_id_value

    def build_dm_code(
        self,
        source: DocumentPipelineOutput,
        mode: FaultMode,
    ) -> DmCode:
        self.calls["build_dm_code"].append((source, mode))
        return self.dm_code_value

    def determine_info_code(self, mode: FaultMode) -> str:
        self.calls["determine_info_code"].append(mode)
        return self.info_code_value

    def resolve_issue_info(self) -> IssueInfo:
        self.calls["resolve_issue_info"].append(())
        return self.issue_info_value

    def resolve_issue_date(self) -> IssueDate:
        self.calls["resolve_issue_date"].append(())
        return self.issue_date_value

    def normalize_title(
        self,
        raw_title: str,
        mode: FaultMode,
    ) -> DmTitle:
        self.calls["normalize_title"].append((raw_title, mode))
        return self.title_value

    def default_language(self) -> Language:
        self.calls["default_language"].append(())
        return self.language_value

    # ── B. Section & mode heuristics (3 methods) ─────────────────

    def fault_relevance_keywords(self) -> frozenset[str]:
        self.calls["fault_relevance_keywords"].append(())
        return self.keywords_value

    def fault_relevant_section_types(self) -> frozenset[str]:
        self.calls["fault_relevant_section_types"].append(())
        return self.section_types_value

    def assess_mode_by_structure(
        self,
        sections: list[Section],
    ) -> FaultMode | None:
        self.calls["assess_mode_by_structure"].append(sections)
        return self.mode_by_structure_value

    # ── C. Table heuristics (2 methods) ──────────────────────────

    def normalize_table_headers(
        self,
        headers: list[str],
    ) -> list[str]:
        self.calls["normalize_table_headers"].append(headers)
        if self.normalized_headers_value is not None:
            return self.normalized_headers_value
        # Default: lowercase the input
        return [h.lower() for h in headers]

    def classify_table_by_headers(
        self,
        normalized_headers: list[str],
    ) -> TableType | None:
        self.calls["classify_table_by_headers"].append(normalized_headers)
        return self.table_by_headers_value

    # ── D. Threshold / configuration lookup (1 method) ───────────

    def llm_confidence_threshold(self, task: str) -> float:
        self.calls["llm_confidence_threshold"].append(task)
        return self.threshold_value

    # ── E. Fault-code derivation (1 method) ──────────────────────

    def derive_fault_code(
        self,
        fault_description: str,
        system_code: str,
    ) -> str:
        self.calls["derive_fault_code"].append(
            (fault_description, system_code),
        )
        return self.fault_code_value
