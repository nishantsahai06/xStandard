"""Unit tests for ``review_gate.default_review_gate``.

Tests the four decision paths:
  Case 1: errors present     → REJECTED, auto_approved=False
  Case 2: warnings + LLM    → NOT_REVIEWED, auto_approved=False
  Case 3: warnings only      → APPROVED, auto_approved=True
  Case 4: clean              → APPROVED, auto_approved=True
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.review_gate import default_review_gate
from fault_mapper.domain.enums import (
    MappingStrategy,
    ReviewStatus,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.value_objects import (
    FieldOrigin,
    MappingTrace,
)

from tests.fixtures.validation_fixtures import (
    make_clean_validation_result,
    make_error_validation_result,
    make_warning_validation_result,
    make_biz_error_validation_result,
    make_trace_high_confidence,
    make_trace_low_confidence_llm,
    make_valid_fault_reporting_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  CASE 1: ERRORS → REJECTED
# ═══════════════════════════════════════════════════════════════════════


class TestReviewGateRejected:
    """Validation with errors → REJECTED."""

    def test_schema_errors_rejected(self) -> None:
        module = make_valid_fault_reporting_module()
        result = make_error_validation_result()
        decision = default_review_gate(module, result)

        assert decision.review_status is ReviewStatus.REJECTED
        assert decision.auto_approved is False
        assert decision.validation_status is ValidationStatus.SCHEMA_FAILED

    def test_business_errors_rejected(self) -> None:
        module = make_valid_fault_reporting_module()
        result = make_biz_error_validation_result()
        decision = default_review_gate(module, result)

        assert decision.review_status is ReviewStatus.REJECTED
        assert decision.auto_approved is False

    def test_reasons_contain_error_codes(self) -> None:
        module = make_valid_fault_reporting_module()
        result = make_error_validation_result()
        decision = default_review_gate(module, result)

        reasons_text = " ".join(decision.reasons)
        assert "SCHEMA-001" in reasons_text
        assert "1 total" in reasons_text


# ═══════════════════════════════════════════════════════════════════════
#  CASE 2: WARNINGS + LOW-CONFIDENCE LLM → NOT_REVIEWED
# ═══════════════════════════════════════════════════════════════════════


class TestReviewGateNotReviewed:
    """Warnings + concerning LLM fields → NOT_REVIEWED."""

    def test_warnings_with_low_confidence_llm(self) -> None:
        module = make_valid_fault_reporting_module(
            trace=make_trace_low_confidence_llm(),
        )
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)

        assert decision.review_status is ReviewStatus.NOT_REVIEWED
        assert decision.auto_approved is False

    def test_reasons_mention_llm(self) -> None:
        module = make_valid_fault_reporting_module(
            trace=make_trace_low_confidence_llm(),
        )
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)

        reasons_text = " ".join(decision.reasons)
        assert "LLM" in reasons_text or "llm" in reasons_text


# ═══════════════════════════════════════════════════════════════════════
#  CASE 3: WARNINGS ONLY (no LLM concerns) → APPROVED
# ═══════════════════════════════════════════════════════════════════════


class TestReviewGateApprovedWithAdvisory:
    """Warnings only, no LLM concerns → auto-approved with advisory."""

    def test_warnings_no_llm_auto_approved(self) -> None:
        module = make_valid_fault_reporting_module(trace=None)
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)

        assert decision.review_status is ReviewStatus.APPROVED
        assert decision.auto_approved is True

    def test_warnings_with_high_confidence_llm_approved(self) -> None:
        """High-confidence LLM fields don't block auto-approval."""
        module = make_valid_fault_reporting_module(
            trace=make_trace_high_confidence(),
        )
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)

        assert decision.review_status is ReviewStatus.APPROVED
        assert decision.auto_approved is True

    def test_advisory_in_reasons(self) -> None:
        module = make_valid_fault_reporting_module(trace=None)
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)

        reasons_text = " ".join(decision.reasons)
        assert "advisory" in reasons_text.lower()


# ═══════════════════════════════════════════════════════════════════════
#  CASE 4: CLEAN → APPROVED
# ═══════════════════════════════════════════════════════════════════════


class TestReviewGateClean:
    """Clean validation → auto-approved."""

    def test_clean_approved(self) -> None:
        module = make_valid_fault_reporting_module()
        result = make_clean_validation_result()
        decision = default_review_gate(module, result)

        assert decision.review_status is ReviewStatus.APPROVED
        assert decision.auto_approved is True
        assert decision.validation_status is ValidationStatus.APPROVED

    def test_clean_reasons_mention_passed(self) -> None:
        module = make_valid_fault_reporting_module()
        result = make_clean_validation_result()
        decision = default_review_gate(module, result)

        reasons_text = " ".join(decision.reasons)
        assert "passed" in reasons_text.lower()


# ═══════════════════════════════════════════════════════════════════════
#  LLM FIELD CONCERN EDGE CASES
# ═══════════════════════════════════════════════════════════════════════


class TestReviewGateLlmEdgeCases:
    """Edge cases for _has_concerning_llm_fields."""

    def test_no_trace_not_concerning(self) -> None:
        """Module with trace=None → no LLM concern."""
        module = make_valid_fault_reporting_module(trace=None)
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)
        # Should NOT be NOT_REVIEWED — no trace means no LLM concern
        assert decision.review_status is ReviewStatus.APPROVED

    def test_empty_field_origins_not_concerning(self) -> None:
        """Empty field_origins → no LLM concern."""
        module = make_valid_fault_reporting_module(
            trace=MappingTrace(field_origins={}),
        )
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)
        assert decision.review_status is ReviewStatus.APPROVED

    def test_all_rule_strategy_not_concerning(self) -> None:
        """Only RULE strategy fields → no LLM concern."""
        module = make_valid_fault_reporting_module(
            trace=MappingTrace(
                field_origins={
                    "f1": FieldOrigin(strategy=MappingStrategy.RULE, source_path="x", confidence=0.1),
                    "f2": FieldOrigin(strategy=MappingStrategy.RULE, source_path="y", confidence=0.2),
                },
            ),
        )
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)
        assert decision.review_status is ReviewStatus.APPROVED

    def test_single_low_llm_below_ratio(self) -> None:
        """1 out of 10 LLM fields low-conf → ratio 0.10 ≤ 0.20 threshold → NOT concerning."""
        origins = {}
        for i in range(10):
            conf = 0.3 if i == 0 else 0.9
            origins[f"field_{i}"] = FieldOrigin(
                strategy=MappingStrategy.LLM, source_path="x", confidence=conf,
            )
        module = make_valid_fault_reporting_module(
            trace=MappingTrace(field_origins=origins),
        )
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)
        assert decision.review_status is ReviewStatus.APPROVED

    def test_high_ratio_low_llm_concerning(self) -> None:
        """3 out of 4 LLM fields low-conf → ratio 0.75 > 0.20 → concerning."""
        origins = {
            "a": FieldOrigin(strategy=MappingStrategy.LLM, source_path="x", confidence=0.2),
            "b": FieldOrigin(strategy=MappingStrategy.LLM, source_path="x", confidence=0.3),
            "c": FieldOrigin(strategy=MappingStrategy.LLM, source_path="x", confidence=0.4),
            "d": FieldOrigin(strategy=MappingStrategy.LLM, source_path="x", confidence=0.9),
        }
        module = make_valid_fault_reporting_module(
            trace=MappingTrace(field_origins=origins),
        )
        result = make_warning_validation_result()
        decision = default_review_gate(module, result)
        assert decision.review_status is ReviewStatus.NOT_REVIEWED
