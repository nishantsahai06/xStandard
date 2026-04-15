"""Fake procedural rules engine — in-memory test double for ``ProceduralRulesEnginePort``.

All 12 methods are implemented with sensible defaults.  Every attribute
is public and mutable so tests can override canned values per-scenario.

Call tracking is included: ``calls[method_name]`` holds a list of
argument tuples for every invocation.
"""

from __future__ import annotations

from typing import Any

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


class FakeProceduralRulesEngine:
    """Configurable fake implementing ``ProceduralRulesEnginePort`` (12 methods)."""

    def __init__(self) -> None:
        # ── Canned return values ─────────────────────────────────
        self.record_id_value: str = "proc-test-001"
        self.dm_code_value = DmCode(
            model_ident_code="TESTAC",
            system_diff_code="A",
            system_code="32",
            sub_system_code="00",
            sub_sub_system_code="00",
            assy_code="00",
            disassy_code="A",
            disassy_code_variant="A",
            info_code="200",
            info_code_variant="A",
            item_location_code="A",
        )
        self.info_code_value: str = "200"
        self.issue_info_value = IssueInfo(issue_number="001", in_work="00")
        self.issue_date_value = IssueDate(year="2026", month="06", day="15")
        self.title_value = DmTitle(
            tech_name="Maintenance Procedure",
            info_name="Procedure",
        )
        self.language_value = Language(
            language_iso_code="en",
            country_iso_code="US",
        )
        self.keywords_value: frozenset[str] = frozenset(
            {
                "procedure", "task", "step", "instruction",
                "remove", "install", "inspect", "service",
                "maintenance",
            },
        )
        self.section_types_value: frozenset[str] = frozenset(
            {
                "procedure", "task", "subtask", "maintenance",
                "servicing", "inspection", "removal", "installation",
            },
        )
        self.classify_section_value: ProceduralSectionType | None = None
        self.normalize_step_value: str | None = None  # use input if None
        self.threshold_value: float = 0.80

        # ── Call tracker ─────────────────────────────────────────
        self.calls: dict[str, list[Any]] = {
            "generate_record_id": [],
            "build_dm_code": [],
            "determine_info_code": [],
            "resolve_issue_info": [],
            "resolve_issue_date": [],
            "normalize_title": [],
            "default_language": [],
            "procedural_relevance_keywords": [],
            "procedural_relevant_section_types": [],
            "classify_section_by_structure": [],
            "normalize_step_number": [],
            "llm_confidence_threshold": [],
        }

    # ── A. Header defaults / DM-code assembly (7 methods) ────────

    def generate_record_id(self) -> str:
        self.calls["generate_record_id"].append(())
        return self.record_id_value

    def build_dm_code(
        self,
        source: DocumentPipelineOutput,
        module_type: ProceduralModuleType,
    ) -> DmCode:
        self.calls["build_dm_code"].append((source, module_type))
        return self.dm_code_value

    def determine_info_code(
        self,
        module_type: ProceduralModuleType,
    ) -> str:
        self.calls["determine_info_code"].append(module_type)
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
        module_type: ProceduralModuleType,
    ) -> DmTitle:
        self.calls["normalize_title"].append((raw_title, module_type))
        return self.title_value

    def default_language(self) -> Language:
        self.calls["default_language"].append(())
        return self.language_value

    # ── B. Procedural heuristics (3 methods) ─────────────────────

    def procedural_relevance_keywords(self) -> frozenset[str]:
        self.calls["procedural_relevance_keywords"].append(())
        return self.keywords_value

    def procedural_relevant_section_types(self) -> frozenset[str]:
        self.calls["procedural_relevant_section_types"].append(())
        return self.section_types_value

    def classify_section_by_structure(
        self,
        section: Section,
    ) -> ProceduralSectionType | None:
        self.calls["classify_section_by_structure"].append(section)
        return self.classify_section_value

    # ── C. Step normalisation (1 method) ─────────────────────────

    def normalize_step_number(self, raw_number: str) -> str:
        self.calls["normalize_step_number"].append(raw_number)
        if self.normalize_step_value is not None:
            return self.normalize_step_value
        return raw_number.strip()

    # ── D. Threshold / configuration lookup (1 method) ───────────

    def llm_confidence_threshold(self, task: str) -> float:
        self.calls["llm_confidence_threshold"].append(task)
        return self.threshold_value
