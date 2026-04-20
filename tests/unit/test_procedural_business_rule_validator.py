"""Unit tests for ``procedural_business_rule_validator``.

Tests all 15 BIZ-P-xxx rules aligned to canonical vocabulary.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.procedural_business_rule_validator import (
    validate_procedural_business_rules,
)
from fault_mapper.domain.enums import (
    ClassificationMethod,
    MappingStrategy,
    ValidationSeverity,
)
from fault_mapper.domain.models import Classification, Provenance
from fault_mapper.domain.procedural_enums import (
    ActionType,
    ProceduralSectionType,
)
from fault_mapper.domain.procedural_models import (
    ProceduralContent,
    ProceduralLineage,
    ProceduralReference,
    ProceduralRequirementItem,
    ProceduralSection,
    ProceduralStep,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    FieldOrigin,
    MappingTrace,
    ValidationIssue,
)

from tests.fixtures.procedural_validation_fixtures import (
    make_procedural_dm_code,
    make_procedural_header,
    make_procedural_section,
    make_procedural_step,
    make_procedural_lineage,
    make_procedural_content,
    make_valid_procedural_module,
    make_procedural_module_empty_title,
    make_procedural_module_no_info_name,
    make_procedural_module_unknown_model,
    make_procedural_module_duplicate_orders,
    make_procedural_module_empty_section,
    make_procedural_module_empty_step,
    make_procedural_module_no_lineage,
    make_procedural_module_bad_lineage_method,
    make_procedural_module_low_confidence,
    make_procedural_module_with_low_confidence_trace,
)


# ─── Helpers ─────────────────────────────────────────────────────────

def _codes(issues: list[ValidationIssue]) -> set[str]:
    return {i.code for i in issues}


def _errors(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.is_error]


def _warnings(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.is_warning]


# ═══════════════════════════════════════════════════════════════════════
#  CLEAN MODULE → NO ISSUES
# ═══════════════════════════════════════════════════════════════════════


class TestBizCleanModule:
    """A fully valid module produces zero business-rule issues."""

    def test_no_issues_for_valid_module(self) -> None:
        issues = validate_procedural_business_rules(
            make_valid_procedural_module(),
        )
        assert issues == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-001: techName not empty
# ═══════════════════════════════════════════════════════════════════════


class TestBizP001TechName:
    def test_empty_tech_name_error(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_empty_title(),
        )
        assert "BIZ-P-001" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-001"]
        assert all(i.severity is ValidationSeverity.ERROR for i in matching)

    def test_whitespace_tech_name_error(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                dm_title=DmTitle(tech_name="   ", info_name="Test"),
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-001" in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-002: infoName should be present
# ═══════════════════════════════════════════════════════════════════════


class TestBizP002InfoName:
    def test_missing_info_name_warning(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_no_info_name(),
        )
        assert "BIZ-P-002" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-002"]
        assert all(i.severity is ValidationSeverity.WARNING for i in matching)

    def test_present_info_name_no_issue(self) -> None:
        issues = validate_procedural_business_rules(
            make_valid_procedural_module(),
        )
        assert "BIZ-P-002" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-003: UNKNOWN model ident code
# ═══════════════════════════════════════════════════════════════════════


class TestBizP003UnknownModel:
    def test_unknown_model_warning(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_unknown_model(),
        )
        assert "BIZ-P-003" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-003"]
        assert all(i.severity is ValidationSeverity.WARNING for i in matching)

    def test_known_model_no_issue(self) -> None:
        issues = validate_procedural_business_rules(
            make_valid_procedural_module(),
        )
        assert "BIZ-P-003" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-004: section ordering
# ═══════════════════════════════════════════════════════════════════════


class TestBizP004SectionOrdering:
    def test_duplicate_orders_error(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_duplicate_orders(),
        )
        assert "BIZ-P-004" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-004"]
        assert any(i.is_error for i in matching)

    def test_non_monotonic_warning(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        section_id="sec-2", section_order=2,
                    ),
                    make_procedural_section(
                        section_id="sec-1",
                        title="Second",
                        section_order=1,
                        steps=[make_procedural_step(
                            step_id="s2", step_number="2",
                        )],
                    ),
                ],
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-004" in _codes(issues)

    def test_contiguous_ordering_no_issue(self) -> None:
        issues = validate_procedural_business_rules(
            make_valid_procedural_module(),
        )
        assert "BIZ-P-004" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-005: section must have steps or sub-sections
# ═══════════════════════════════════════════════════════════════════════


class TestBizP005SectionSteps:
    def test_empty_section_warning(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_empty_section(),
        )
        assert "BIZ-P-005" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-005"]
        assert all(i.severity is ValidationSeverity.WARNING for i in matching)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-006: step text not empty
# ═══════════════════════════════════════════════════════════════════════


class TestBizP006StepText:
    def test_empty_step_text_error(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_empty_step(),
        )
        assert "BIZ-P-006" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-006"]
        assert all(i.is_error for i in matching)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-007: step numbering coherent
# ═══════════════════════════════════════════════════════════════════════


class TestBizP007StepNumbering:
    def test_duplicate_step_numbers_warning(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    ProceduralSection(
                        section_id="sec-1",
                        title="Test",
                        section_order=1,
                        section_type=ProceduralSectionType.PROCEDURE,
                        page_numbers=[1],
                        steps=[
                            ProceduralStep(
                                step_id="s1", step_number="1",
                                text="First step",
                            ),
                            ProceduralStep(
                                step_id="s2", step_number="1",
                                text="Duplicate numbered step",
                            ),
                        ],
                    ),
                ],
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-007" in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-008: lineage required fields
# ═══════════════════════════════════════════════════════════════════════


class TestBizP008Lineage:
    def test_missing_lineage_warning(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_no_lineage(),
        )
        assert "BIZ-P-008" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-008"]
        assert all(i.severity is ValidationSeverity.WARNING for i in matching)

    def test_empty_mapped_by_error(self) -> None:
        m = make_valid_procedural_module(
            lineage=make_procedural_lineage(mapped_by=""),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-008" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-008"]
        assert any(i.is_error for i in matching)

    def test_empty_mapped_at_error(self) -> None:
        m = make_valid_procedural_module(
            lineage=make_procedural_lineage(mapped_at=""),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-008" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-008"]
        assert any(i.is_error for i in matching)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-009: lineage mapping method canonical
# ═══════════════════════════════════════════════════════════════════════


class TestBizP009MappingMethod:
    def test_unknown_method_warning(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_bad_lineage_method(),
        )
        assert "BIZ-P-009" in _codes(issues)

    def test_known_domain_method_no_issue(self) -> None:
        """'rules' is a valid domain value that maps to canonical 'rules-only'."""
        issues = validate_procedural_business_rules(
            make_valid_procedural_module(),
        )
        assert "BIZ-P-009" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-010: requirement type canonical
# ═══════════════════════════════════════════════════════════════════════


class TestBizP010RequirementType:
    def test_unknown_req_type_warning(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[make_procedural_section()],
                preliminary_requirements=[
                    ProceduralRequirementItem(
                        requirement_type="exotic",
                        name="X",
                    ),
                ],
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-010" in _codes(issues)

    def test_known_req_type_no_issue(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[make_procedural_section()],
                preliminary_requirements=[
                    ProceduralRequirementItem(
                        requirement_type="equipment",
                        name="Wrench",
                    ),
                ],
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-010" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-011: reference type canonical
# ═══════════════════════════════════════════════════════════════════════


class TestBizP011ReferenceType:
    def test_empty_ref_type_error(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        references=[
                            ProceduralReference(ref_type="", label="X"),
                        ],
                    ),
                ],
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-011" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-011"]
        assert any(i.is_error for i in matching)

    def test_unknown_ref_type_warning(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        references=[
                            ProceduralReference(
                                ref_type="bizarre", label="Y",
                            ),
                        ],
                    ),
                ],
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-011" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-011"]
        assert any(i.is_warning for i in matching)

    def test_known_domain_ref_type_no_issue(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        references=[
                            ProceduralReference(
                                ref_type="dm_ref",
                                target_dm_code="DMC-TEST",
                            ),
                        ],
                    ),
                ],
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-011" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-012: LLM trace confidence
# ═══════════════════════════════════════════════════════════════════════


class TestBizP012TraceConfidence:
    def test_low_llm_confidence_warning(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_with_low_confidence_trace(),
        )
        assert "BIZ-P-012" in _codes(issues)
        matching = [i for i in issues if i.code == "BIZ-P-012"]
        assert all(i.severity is ValidationSeverity.WARNING for i in matching)

    def test_no_trace_no_issue(self) -> None:
        """No trace at all → skip BIZ-P-012."""
        m = make_valid_procedural_module()
        m.trace = None
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-012" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-013: classification confidence
# ═══════════════════════════════════════════════════════════════════════


class TestBizP013ClassificationConfidence:
    def test_low_classification_confidence_warning(self) -> None:
        issues = validate_procedural_business_rules(
            make_procedural_module_low_confidence(),
        )
        assert "BIZ-P-013" in _codes(issues)

    def test_no_classification_no_issue(self) -> None:
        m = make_valid_procedural_module()
        m.classification = None
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-013" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-014: section type maps to canonical
# ═══════════════════════════════════════════════════════════════════════


class TestBizP014SectionType:
    def test_all_known_types_no_issue(self) -> None:
        """All domain ProceduralSectionType values are in the mapping."""
        issues = validate_procedural_business_rules(
            make_valid_procedural_module(),
        )
        assert "BIZ-P-014" not in _codes(issues)


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-P-015: security classification canonical
# ═══════════════════════════════════════════════════════════════════════


class TestBizP015SecurityClassification:
    def test_non_canonical_classification_warning(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                security_classification="top-secret",
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-015" in _codes(issues)

    def test_canonical_classification_no_issue(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                security_classification="02-restricted",
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-015" not in _codes(issues)

    def test_none_classification_no_issue(self) -> None:
        """None → serializer defaults to '01-unclassified' which is canonical."""
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                security_classification=None,
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert "BIZ-P-015" not in _codes(issues)
