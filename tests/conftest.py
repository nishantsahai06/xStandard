"""Shared pytest fixtures and factory helpers for fault-mapper tests.

All factories return **minimal, valid** domain objects.  Tests that need
non-default values should override individual fields via keyword args.

No infrastructure, no real adapters, no network — fakes only.
"""

from __future__ import annotations

import pytest
from typing import Any

from fault_mapper.domain.enums import (
    FaultEntryType,
    FaultMode,
    MappingStrategy,
    ReviewStatus,
    TableType,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    Chunk,
    CommonInfo,
    DetectedLruItem,
    DetectionInfo,
    DocumentPipelineOutput,
    FaultContent,
    FaultDescription,
    FaultEntry,
    FaultHeader,
    FaultIsolationContent,
    FaultReportingContent,
    FigureRef,
    ImageAsset,
    IsolationStep,
    LocateAndRepair,
    LocateAndRepairLruItem,
    Lru,
    Metadata,
    Repair,
    SchematicComponent,
    SchematicsItem,
    Section,
    Sru,
    TableAsset,
    TypedText,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    FieldOrigin,
    IssueDate,
    IssueInfo,
    Language,
    MappingTrace,
)

# Re-export fakes so tests can do ``from conftest import ...`` or fixtures
from tests.fakes.fake_llm_interpreter import FakeLlmInterpreter
from tests.fakes.fake_rules_engine import FakeRulesEngine
from tests.fakes.fake_mapping_review_policy import FakeMappingReviewPolicy
from tests.fakes.fake_procedural_rules_engine import FakeProceduralRulesEngine
from tests.fakes.fake_procedural_llm_interpreter import (
    FakeProceduralLlmInterpreter,
)


# ═══════════════════════════════════════════════════════════════════════
#  A.  SOURCE-SIDE FACTORIES
# ═══════════════════════════════════════════════════════════════════════


def make_chunk(
    *,
    chunk_text: str = "Sample chunk text.",
    original_text: str | None = None,
    contextual_prefix: str = "",
    id: str | None = "chunk-1",
    **kwargs: Any,
) -> Chunk:
    return Chunk(
        chunk_text=chunk_text,
        original_text=original_text or chunk_text,
        contextual_prefix=contextual_prefix,
        id=id,
        **kwargs,
    )


def make_table(
    *,
    caption: str | None = "Test Table",
    headers: list[str] | None = None,
    rows: list[list[str]] | None = None,
    markdown_summary: str | None = None,
    id: str | None = "table-1",
    page_number: int | None = 1,
    **kwargs: Any,
) -> TableAsset:
    return TableAsset(
        caption=caption,
        headers=headers or [],
        rows=rows or [],
        markdown_summary=markdown_summary,
        id=id,
        page_number=page_number,
        **kwargs,
    )


def make_image(
    *,
    caption: str | None = "Test Image",
    id: str | None = "img-1",
    page_number: int | None = 1,
    **kwargs: Any,
) -> ImageAsset:
    return ImageAsset(
        caption=caption,
        id=id,
        page_number=page_number,
        **kwargs,
    )


def make_section(
    *,
    section_title: str = "Fault Reporting",
    section_order: int = 0,
    section_type: str = "fault_reporting",
    section_text: str = "A fault was detected in the LRU.",
    level: int = 1,
    page_numbers: list[int] | None = None,
    chunks: list[Chunk] | None = None,
    images: list[ImageAsset] | None = None,
    tables: list[TableAsset] | None = None,
    id: str | None = "sec-1",
) -> Section:
    return Section(
        section_title=section_title,
        section_order=section_order,
        section_type=section_type,
        section_text=section_text,
        level=level,
        page_numbers=page_numbers or [1, 2],
        chunks=chunks if chunks is not None else [make_chunk()],
        images=images or [],
        tables=tables or [],
        id=id,
    )


def make_schematic_component(
    *,
    name: str = "Resistor R1",
    component_type: str | None = "resistor",
    reference_designator: str | None = "R1",
) -> SchematicComponent:
    return SchematicComponent(
        name=name,
        component_type=component_type,
        reference_designator=reference_designator,
    )


def make_schematic(
    *,
    page_number: int = 5,
    components: list[SchematicComponent] | None = None,
    source_path: str | None = "/schematics/sch1.png",
    id: str | None = "sch-1",
) -> SchematicsItem:
    return SchematicsItem(
        page_number=page_number,
        components=components or [make_schematic_component()],
        source_path=source_path,
        id=id,
    )


def make_source(
    *,
    id: str = "doc-001",
    full_text: str = "Full document text with fault and troubleshooting data.",
    file_name: str = "B737-FaultReport.pdf",
    file_type: str = "pdf",
    source_path: str = "/uploads/B737-FaultReport.pdf",
    sections: list[Section] | None = None,
    schematics: list[SchematicsItem] | None = None,
) -> DocumentPipelineOutput:
    return DocumentPipelineOutput(
        id=id,
        full_text=full_text,
        file_name=file_name,
        file_type=file_type,
        source_path=source_path,
        metadata=Metadata(),
        sections=sections if sections is not None else [make_section()],
        schematics=schematics or [],
    )


# ═══════════════════════════════════════════════════════════════════════
#  B.  TARGET-SIDE FACTORIES
# ═══════════════════════════════════════════════════════════════════════


def make_dm_code(**overrides: Any) -> DmCode:
    defaults = dict(
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
    defaults.update(overrides)
    return DmCode(**defaults)


def make_language() -> Language:
    return Language(language_iso_code="en", country_iso_code="US")


def make_issue_info() -> IssueInfo:
    return IssueInfo(issue_number="001", in_work="00")


def make_issue_date() -> IssueDate:
    return IssueDate(year="2026", month="04", day="13")


def make_dm_title(
    tech_name: str = "Fault Report",
    info_name: str | None = "Fault Reporting",
) -> DmTitle:
    return DmTitle(tech_name=tech_name, info_name=info_name)


def make_header(**overrides: Any) -> FaultHeader:
    defaults = dict(
        dm_code=make_dm_code(),
        language=make_language(),
        issue_info=make_issue_info(),
        issue_date=make_issue_date(),
        dm_title=make_dm_title(),
    )
    defaults.update(overrides)
    return FaultHeader(**defaults)


def make_field_origin(
    *,
    strategy: MappingStrategy = MappingStrategy.RULE,
    source_path: str = "test",
    confidence: float = 1.0,
    source_chunk_id: str | None = None,
) -> FieldOrigin:
    return FieldOrigin(
        strategy=strategy,
        source_path=source_path,
        confidence=confidence,
        source_chunk_id=source_chunk_id,
    )


def make_mapping_trace(
    *,
    field_origins: dict[str, FieldOrigin] | None = None,
    warnings: list[str] | None = None,
) -> MappingTrace:
    return MappingTrace(
        field_origins=field_origins or {},
        warnings=warnings or [],
    )


# ═══════════════════════════════════════════════════════════════════════
#  C.  FAKE / PORT FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_llm() -> FakeLlmInterpreter:
    """Return a fresh ``FakeLlmInterpreter`` with sensible defaults."""
    return FakeLlmInterpreter()


@pytest.fixture
def fake_rules() -> FakeRulesEngine:
    """Return a fresh ``FakeRulesEngine`` with sensible defaults."""
    return FakeRulesEngine()


@pytest.fixture
def fake_review_policy() -> FakeMappingReviewPolicy:
    """Return a ``FakeMappingReviewPolicy`` that auto-approves."""
    return FakeMappingReviewPolicy()


# ═══════════════════════════════════════════════════════════════════════
#  D.  PROCEDURAL FAKE / PORT FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_procedural_llm() -> FakeProceduralLlmInterpreter:
    """Return a fresh ``FakeProceduralLlmInterpreter`` with sensible defaults."""
    return FakeProceduralLlmInterpreter()


@pytest.fixture
def fake_procedural_rules() -> FakeProceduralRulesEngine:
    """Return a fresh ``FakeProceduralRulesEngine`` with sensible defaults."""
    return FakeProceduralRulesEngine()
