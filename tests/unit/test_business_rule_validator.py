"""Unit tests for ``business_rule_validator.validate_business_rules``.

Each BIZ-* check is tested independently using tailored fixtures.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.business_rule_validator import (
    validate_business_rules,
)
from fault_mapper.domain.enums import (
    ClassificationMethod,
    FaultEntryType,
    FaultMode,
    MappingStrategy,
    ValidationSeverity,
)
from fault_mapper.domain.models import (
    Classification,
    FaultContent,
    FaultDescription,
    FaultEntry,
    FaultIsolationContent,
    FaultReportingContent,
    IsolationStep,
    S1000DFaultDataModule,
)
from fault_mapper.domain.value_objects import FieldOrigin, MappingTrace

from tests.fixtures.validation_fixtures import (
    make_module_biz_info_code_mismatch,
    make_module_biz_invalid_ilc,
    make_module_biz_bad_info_code_length,
    make_module_biz_low_classification_confidence,
    make_module_biz_missing_fault_code,
    make_module_biz_missing_fault_descr,
    make_module_biz_missing_id_for_isolated,
    make_module_biz_question_without_branches,
    make_module_biz_unknown_model_ident,
    make_module_with_low_confidence_trace,
    make_module_with_unmapped_sources,
    make_valid_dm_code,
    make_valid_fault_isolation_module,
    make_valid_fault_reporting_module,
    make_valid_header,
)


# ═══════════════════════════════════════════════════════════════════════
#  HAPPY PATH — zero issues
# ═══════════════════════════════════════════════════════════════════════


class TestBusinessRulesHappyPath:
    """Clean modules produce zero business-rule issues."""

    def test_valid_reporting_module(self) -> None:
        issues = validate_business_rules(make_valid_fault_reporting_module())
        assert issues == []

    def test_valid_isolation_module(self) -> None:
        issues = validate_business_rules(make_valid_fault_isolation_module())
        assert issues == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-001: ITEM LOCATION CODE
# ═══════════════════════════════════════════════════════════════════════


class TestBiz001ItemLocationCode:
    """BIZ-001: item_location_code not in {A, B, C, D, T} → ERROR."""

    def test_invalid_ilc(self) -> None:
        module = make_module_biz_invalid_ilc()
        issues = validate_business_rules(module)
        biz001 = [i for i in issues if i.code == "BIZ-001"]
        assert len(biz001) == 1
        assert biz001[0].severity is ValidationSeverity.ERROR
        assert "Z" in biz001[0].message

    @pytest.mark.parametrize("valid_ilc", ["A", "B", "C", "D", "T"])
    def test_valid_ilc_no_issue(self, valid_ilc: str) -> None:
        module = make_valid_fault_reporting_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(item_location_code=valid_ilc),
            ),
        )
        issues = validate_business_rules(module)
        biz001 = [i for i in issues if i.code == "BIZ-001"]
        assert biz001 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-002: INFO CODE LENGTH
# ═══════════════════════════════════════════════════════════════════════


class TestBiz002InfoCodeLength:
    """BIZ-002: info_code length ≠ 3 → ERROR."""

    def test_short_info_code(self) -> None:
        module = make_module_biz_bad_info_code_length()
        issues = validate_business_rules(module)
        biz002 = [i for i in issues if i.code == "BIZ-002"]
        assert len(biz002) == 1
        assert biz002[0].severity is ValidationSeverity.ERROR

    def test_long_info_code(self) -> None:
        module = make_valid_fault_reporting_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(info_code="0310"),
            ),
        )
        issues = validate_business_rules(module)
        biz002 = [i for i in issues if i.code == "BIZ-002"]
        assert len(biz002) == 1

    def test_exact_3_chars_no_issue(self) -> None:
        module = make_valid_fault_reporting_module()
        issues = validate_business_rules(module)
        biz002 = [i for i in issues if i.code == "BIZ-002"]
        assert biz002 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-003: INFO CODE vs MODE CONSISTENCY
# ═══════════════════════════════════════════════════════════════════════


class TestBiz003InfoCodeModeConsistency:
    """BIZ-003: info_code inconsistent with module mode → WARNING."""

    def test_reporting_with_isolation_code(self) -> None:
        module = make_module_biz_info_code_mismatch()
        issues = validate_business_rules(module)
        biz003 = [i for i in issues if i.code == "BIZ-003"]
        assert len(biz003) == 1
        assert biz003[0].severity is ValidationSeverity.WARNING

    def test_isolation_with_reporting_code(self) -> None:
        module = make_valid_fault_isolation_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(info_code="031"),
            ),
        )
        issues = validate_business_rules(module)
        biz003 = [i for i in issues if i.code == "BIZ-003"]
        assert len(biz003) == 1

    @pytest.mark.parametrize("code", ["031", "030", "033"])
    def test_valid_reporting_codes(self, code: str) -> None:
        module = make_valid_fault_reporting_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(info_code=code),
            ),
        )
        issues = validate_business_rules(module)
        biz003 = [i for i in issues if i.code == "BIZ-003"]
        assert biz003 == []

    @pytest.mark.parametrize("code", ["032", "034"])
    def test_valid_isolation_codes(self, code: str) -> None:
        module = make_valid_fault_isolation_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(info_code=code),
            ),
        )
        issues = validate_business_rules(module)
        biz003 = [i for i in issues if i.code == "BIZ-003"]
        assert biz003 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-004: MISSING FAULT CODE
# ═══════════════════════════════════════════════════════════════════════


class TestBiz004MissingFaultCode:
    """BIZ-004: fault entry without fault_code → WARNING."""

    def test_missing_fault_code(self) -> None:
        module = make_module_biz_missing_fault_code()
        issues = validate_business_rules(module)
        biz004 = [i for i in issues if i.code == "BIZ-004"]
        assert len(biz004) == 1
        assert biz004[0].severity is ValidationSeverity.WARNING

    def test_present_fault_code_no_issue(self) -> None:
        module = make_valid_fault_reporting_module()
        issues = validate_business_rules(module)
        biz004 = [i for i in issues if i.code == "BIZ-004"]
        assert biz004 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-005: MISSING FAULT DESCRIPTION
# ═══════════════════════════════════════════════════════════════════════


class TestBiz005MissingFaultDescr:
    """BIZ-005: fault entry without fault_descr → WARNING."""

    def test_missing_fault_descr(self) -> None:
        module = make_module_biz_missing_fault_descr()
        issues = validate_business_rules(module)
        biz005 = [i for i in issues if i.code == "BIZ-005"]
        assert len(biz005) == 1
        assert biz005[0].severity is ValidationSeverity.WARNING

    def test_empty_descr_text(self) -> None:
        """Empty descr string also triggers BIZ-005."""
        module = make_valid_fault_reporting_module(
            content=FaultContent(
                refs=[], warnings_and_cautions=[],
                fault_reporting=FaultReportingContent(
                    fault_entries=[
                        FaultEntry(
                            entry_type=FaultEntryType.DETECTED_FAULT,
                            fault_code="FC001",
                            fault_descr=FaultDescription(descr=""),
                        ),
                    ],
                ),
            ),
        )
        issues = validate_business_rules(module)
        biz005 = [i for i in issues if i.code == "BIZ-005"]
        assert len(biz005) == 1


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-006: ID REQUIRED FOR NON-DETECTED FAULT TYPES
# ═══════════════════════════════════════════════════════════════════════


class TestBiz006MissingIdForNonDetected:
    """BIZ-006: non-detected fault type without ID → WARNING."""

    def test_isolated_fault_missing_id(self) -> None:
        module = make_module_biz_missing_id_for_isolated()
        issues = validate_business_rules(module)
        biz006 = [i for i in issues if i.code == "BIZ-006"]
        assert len(biz006) == 1
        assert biz006[0].severity is ValidationSeverity.WARNING

    @pytest.mark.parametrize("entry_type", [
        FaultEntryType.ISOLATED_FAULT,
        FaultEntryType.ISOLATED_FAULT_ALTS,
        FaultEntryType.OBSERVED_FAULT,
        FaultEntryType.OBSERVED_FAULT_ALTS,
        FaultEntryType.CORRELATED_FAULT,
        FaultEntryType.CORRELATED_FAULT_ALTS,
    ])
    def test_all_id_required_types(self, entry_type: FaultEntryType) -> None:
        module = make_valid_fault_reporting_module(
            content=FaultContent(
                refs=[], warnings_and_cautions=[],
                fault_reporting=FaultReportingContent(
                    fault_entries=[
                        FaultEntry(
                            entry_type=entry_type,
                            id=None,
                            fault_code="FC001",
                            fault_descr=FaultDescription(descr="Test"),
                        ),
                    ],
                ),
            ),
        )
        issues = validate_business_rules(module)
        biz006 = [i for i in issues if i.code == "BIZ-006"]
        assert len(biz006) == 1

    def test_detected_fault_no_id_ok(self) -> None:
        """DETECTED_FAULT does NOT require ID."""
        module = make_valid_fault_reporting_module(
            content=FaultContent(
                refs=[], warnings_and_cautions=[],
                fault_reporting=FaultReportingContent(
                    fault_entries=[
                        FaultEntry(
                            entry_type=FaultEntryType.DETECTED_FAULT,
                            id=None,
                            fault_code="FC001",
                            fault_descr=FaultDescription(descr="Test"),
                        ),
                    ],
                ),
            ),
        )
        issues = validate_business_rules(module)
        biz006 = [i for i in issues if i.code == "BIZ-006"]
        assert biz006 == []

    def test_id_present_no_issue(self) -> None:
        """When ID is present, no BIZ-006 even for id-required types."""
        module = make_valid_fault_reporting_module(
            content=FaultContent(
                refs=[], warnings_and_cautions=[],
                fault_reporting=FaultReportingContent(
                    fault_entries=[
                        FaultEntry(
                            entry_type=FaultEntryType.ISOLATED_FAULT,
                            id="fault-001",
                            fault_code="FC001",
                            fault_descr=FaultDescription(descr="Test"),
                        ),
                    ],
                ),
            ),
        )
        issues = validate_business_rules(module)
        biz006 = [i for i in issues if i.code == "BIZ-006"]
        assert biz006 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-008: QUESTION WITHOUT BRANCHES
# ═══════════════════════════════════════════════════════════════════════


class TestBiz008QuestionWithoutBranches:
    """BIZ-008: isolation step with question but no branches → WARNING."""

    def test_question_without_branches(self) -> None:
        module = make_module_biz_question_without_branches()
        issues = validate_business_rules(module)
        biz008 = [i for i in issues if i.code == "BIZ-008"]
        assert len(biz008) == 1
        assert biz008[0].severity is ValidationSeverity.WARNING

    def test_question_with_branches_ok(self) -> None:
        from fault_mapper.domain.models import IsolationStepBranch
        module = make_valid_fault_isolation_module(
            content=FaultContent(
                refs=[], warnings_and_cautions=[],
                fault_isolation=FaultIsolationContent(
                    fault_isolation_steps=[
                        IsolationStep(
                            step_number=1,
                            instruction="Check power.",
                            question="Is power on?",
                            yes_group=IsolationStepBranch(next_steps=[
                                IsolationStep(step_number=2, instruction="OK."),
                            ]),
                        ),
                    ],
                ),
            ),
        )
        issues = validate_business_rules(module)
        biz008 = [i for i in issues if i.code == "BIZ-008"]
        assert biz008 == []

    def test_no_question_no_issue(self) -> None:
        """Step without question never triggers BIZ-008."""
        issues = validate_business_rules(make_valid_fault_isolation_module())
        biz008 = [i for i in issues if i.code == "BIZ-008"]
        assert biz008 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-009: UNMAPPED SOURCES
# ═══════════════════════════════════════════════════════════════════════


class TestBiz009UnmappedSources:
    """BIZ-009: trace with unmapped sources → WARNING."""

    def test_unmapped_sources(self) -> None:
        module = make_module_with_unmapped_sources()
        issues = validate_business_rules(module)
        biz009 = [i for i in issues if i.code == "BIZ-009"]
        assert len(biz009) == 1
        assert biz009[0].severity is ValidationSeverity.WARNING
        assert "2" in biz009[0].message  # 2 unmapped sources

    def test_no_trace_no_issue(self) -> None:
        module = make_valid_fault_reporting_module(trace=None)
        issues = validate_business_rules(module)
        biz009 = [i for i in issues if i.code == "BIZ-009"]
        assert biz009 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-010: LOW-CONFIDENCE LLM FIELDS
# ═══════════════════════════════════════════════════════════════════════


class TestBiz010LowConfidenceLlm:
    """BIZ-010: LLM fields below 0.5 confidence → WARNING."""

    def test_low_confidence_llm(self) -> None:
        module = make_module_with_low_confidence_trace()
        issues = validate_business_rules(module)
        biz010 = [i for i in issues if i.code == "BIZ-010"]
        assert len(biz010) == 1
        assert biz010[0].severity is ValidationSeverity.WARNING

    def test_high_confidence_llm_ok(self) -> None:
        from tests.fixtures.validation_fixtures import make_trace_high_confidence
        module = make_valid_fault_reporting_module(
            trace=make_trace_high_confidence(),
        )
        issues = validate_business_rules(module)
        biz010 = [i for i in issues if i.code == "BIZ-010"]
        assert biz010 == []

    def test_rule_strategy_not_checked(self) -> None:
        """RULE strategy fields don't trigger BIZ-010 even at low conf."""
        trace = MappingTrace(
            field_origins={
                "field_a": FieldOrigin(
                    strategy=MappingStrategy.RULE,
                    source_path="x",
                    confidence=0.1,  # low, but strategy is RULE
                ),
            },
        )
        module = make_valid_fault_reporting_module(trace=trace)
        issues = validate_business_rules(module)
        biz010 = [i for i in issues if i.code == "BIZ-010"]
        assert biz010 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-011: PLACEHOLDER MODEL IDENT CODE
# ═══════════════════════════════════════════════════════════════════════


class TestBiz011UnknownModelIdent:
    """BIZ-011: model_ident_code == 'UNKNOWN' → WARNING."""

    def test_unknown_model_ident(self) -> None:
        module = make_module_biz_unknown_model_ident()
        issues = validate_business_rules(module)
        biz011 = [i for i in issues if i.code == "BIZ-011"]
        assert len(biz011) == 1
        assert biz011[0].severity is ValidationSeverity.WARNING

    def test_normal_model_ident_ok(self) -> None:
        issues = validate_business_rules(make_valid_fault_reporting_module())
        biz011 = [i for i in issues if i.code == "BIZ-011"]
        assert biz011 == []


# ═══════════════════════════════════════════════════════════════════════
#  BIZ-012: LOW CLASSIFICATION CONFIDENCE
# ═══════════════════════════════════════════════════════════════════════


class TestBiz012LowClassificationConfidence:
    """BIZ-012: classification confidence < 0.3 → WARNING."""

    def test_low_confidence(self) -> None:
        module = make_module_biz_low_classification_confidence()
        issues = validate_business_rules(module)
        biz012 = [i for i in issues if i.code == "BIZ-012"]
        assert len(biz012) == 1
        assert biz012[0].severity is ValidationSeverity.WARNING

    def test_high_confidence_ok(self) -> None:
        module = make_valid_fault_reporting_module(
            classification=Classification(
                domain="S1000D", confidence=0.9, method=ClassificationMethod.RULES,
            ),
        )
        issues = validate_business_rules(module)
        biz012 = [i for i in issues if i.code == "BIZ-012"]
        assert biz012 == []

    def test_threshold_boundary(self) -> None:
        """Exactly 0.3 should NOT trigger BIZ-012 (only < 0.3)."""
        module = make_valid_fault_reporting_module(
            classification=Classification(
                domain="S1000D", confidence=0.3, method=ClassificationMethod.LLM,
            ),
        )
        issues = validate_business_rules(module)
        biz012 = [i for i in issues if i.code == "BIZ-012"]
        assert biz012 == []

    def test_no_classification_no_issue(self) -> None:
        module = make_valid_fault_reporting_module(classification=None)
        issues = validate_business_rules(module)
        biz012 = [i for i in issues if i.code == "BIZ-012"]
        assert biz012 == []


# ═══════════════════════════════════════════════════════════════════════
#  NO-HEADER GUARD
# ═══════════════════════════════════════════════════════════════════════


class TestBusinessRulesNoHeader:
    """Module with header=None should not crash the business validator."""

    def test_no_header_skip_dm_code_checks(self) -> None:
        module = make_valid_fault_reporting_module(header=None)
        # Should not raise — dm_code checks are skipped
        issues = validate_business_rules(module)
        # No BIZ-001/002/003/011 since header is None
        dm_codes = [i for i in issues if i.code in ("BIZ-001", "BIZ-002", "BIZ-003", "BIZ-011")]
        assert dm_codes == []


# ═══════════════════════════════════════════════════════════════════════
#  MULTIPLE ISSUES IN ONE MODULE
# ═══════════════════════════════════════════════════════════════════════


class TestMultipleBusinessIssues:
    """A single module can trigger multiple BIZ-* checks."""

    def test_missing_code_and_descr(self) -> None:
        """Entry with no fault_code AND no fault_descr → BIZ-004 + BIZ-005."""
        module = make_valid_fault_reporting_module(
            content=FaultContent(
                refs=[], warnings_and_cautions=[],
                fault_reporting=FaultReportingContent(
                    fault_entries=[
                        FaultEntry(
                            entry_type=FaultEntryType.DETECTED_FAULT,
                            fault_code=None,
                            fault_descr=None,
                        ),
                    ],
                ),
            ),
        )
        issues = validate_business_rules(module)
        codes = {i.code for i in issues}
        assert "BIZ-004" in codes
        assert "BIZ-005" in codes
