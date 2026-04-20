"""Unit tests for ``procedural_review_gate``.

Tests the 4-case deterministic review decision logic:
  1. Errors → REJECTED
  2. Warnings + low-confidence LLM → NOT_REVIEWED
  3. Warnings only → APPROVED (advisory)
  4. Clean → APPROVED (auto)
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.procedural_review_gate import (
    procedural_review_gate,
)
from fault_mapper.domain.enums import (
    MappingStrategy,
    ReviewStatus,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.value_objects import (
    FieldOrigin,
    MappingTrace,
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)

from tests.fixtures.procedural_validation_fixtures import (
    make_valid_procedural_module,
    make_procedural_clean_result,
    make_procedural_error_result,
    make_procedural_warning_result,
    make_procedural_trace_high_confidence,
    make_procedural_trace_low_confidence,
)


# ─── Helpers ─────────────────────────────────────────────────────────


def _make_error_result() -> ModuleValidationResult:
    return ModuleValidationResult(
        structural_issues=[
            ValidationIssue(
                code="SCHEMA-001",
                severity=ValidationSeverity.ERROR,
                message="Required missing.",
            ),
        ],
        business_issues=[],
        status=ValidationStatus.SCHEMA_FAILED,
    )


def _make_warning_result() -> ModuleValidationResult:
    return ModuleValidationResult(
        structural_issues=[],
        business_issues=[
            ValidationIssue(
                code="BIZ-P-002",
                severity=ValidationSeverity.WARNING,
                message="infoName not set.",
            ),
        ],
        status=ValidationStatus.REVIEW_REQUIRED,
    )


def _make_clean_result() -> ModuleValidationResult:
    return ModuleValidationResult(
        structural_issues=[],
        business_issues=[],
        status=ValidationStatus.APPROVED,
    )


# ═══════════════════════════════════════════════════════════════════════
#  CASE 1: ERRORS → REJECTED
# ═══════════════════════════════════════════════════════════════════════


class TestGateRejected:
    """Errors cause REJECTED status."""

    def test_errors_produce_rejected(self) -> None:
        module = make_valid_procedural_module()
        decision = procedural_review_gate(module, _make_error_result())
        assert decision.review_status is ReviewStatus.REJECTED

    def test_rejected_not_auto_approved(self) -> None:
        module = make_valid_procedural_module()
        decision = procedural_review_gate(module, _make_error_result())
        assert decision.auto_approved is False

    def test_rejected_has_reasons(self) -> None:
        module = make_valid_procedural_module()
        decision = procedural_review_gate(module, _make_error_result())
        assert len(decision.reasons) >= 1
        assert "SCHEMA-001" in decision.reasons[0]


# ═══════════════════════════════════════════════════════════════════════
#  CASE 2: WARNINGS + LOW LLM → NOT_REVIEWED
# ═══════════════════════════════════════════════════════════════════════


class TestGateNotReviewed:
    """Warnings with low-confidence LLM → human review needed."""

    def test_warnings_with_low_llm_not_reviewed(self) -> None:
        module = make_valid_procedural_module()
        module.trace = make_procedural_trace_low_confidence()
        decision = procedural_review_gate(module, _make_warning_result())
        assert decision.review_status is ReviewStatus.NOT_REVIEWED

    def test_not_reviewed_not_auto_approved(self) -> None:
        module = make_valid_procedural_module()
        module.trace = make_procedural_trace_low_confidence()
        decision = procedural_review_gate(module, _make_warning_result())
        assert decision.auto_approved is False


# ═══════════════════════════════════════════════════════════════════════
#  CASE 3: WARNINGS ONLY → APPROVED (advisory)
# ═══════════════════════════════════════════════════════════════════════


class TestGateWarningsApproved:
    """Warnings without LLM concern → auto-approved with advisory."""

    def test_warnings_no_llm_approved(self) -> None:
        module = make_valid_procedural_module()
        module.trace = None  # No LLM involvement
        decision = procedural_review_gate(module, _make_warning_result())
        assert decision.review_status is ReviewStatus.APPROVED

    def test_advisory_auto_approved(self) -> None:
        module = make_valid_procedural_module()
        module.trace = None
        decision = procedural_review_gate(module, _make_warning_result())
        assert decision.auto_approved is True

    def test_warnings_with_high_llm_still_approved(self) -> None:
        module = make_valid_procedural_module()
        module.trace = make_procedural_trace_high_confidence()
        decision = procedural_review_gate(module, _make_warning_result())
        assert decision.review_status is ReviewStatus.APPROVED


# ═══════════════════════════════════════════════════════════════════════
#  CASE 4: CLEAN → APPROVED
# ═══════════════════════════════════════════════════════════════════════


class TestGateClean:
    """Clean validation → auto-approved."""

    def test_clean_approved(self) -> None:
        module = make_valid_procedural_module()
        decision = procedural_review_gate(module, _make_clean_result())
        assert decision.review_status is ReviewStatus.APPROVED

    def test_clean_auto_approved(self) -> None:
        module = make_valid_procedural_module()
        decision = procedural_review_gate(module, _make_clean_result())
        assert decision.auto_approved is True

    def test_clean_has_reasons(self) -> None:
        module = make_valid_procedural_module()
        decision = procedural_review_gate(module, _make_clean_result())
        assert len(decision.reasons) >= 1


# ═══════════════════════════════════════════════════════════════════════
#  DECISION STRUCTURE
# ═══════════════════════════════════════════════════════════════════════


class TestGateDecisionStructure:
    """ReviewDecision has proper fields."""

    def test_decision_has_validation_status(self) -> None:
        module = make_valid_procedural_module()
        decision = procedural_review_gate(module, _make_clean_result())
        assert decision.validation_status is not None

    def test_decision_reasons_are_strings(self) -> None:
        module = make_valid_procedural_module()
        decision = procedural_review_gate(module, _make_error_result())
        for reason in decision.reasons:
            assert isinstance(reason, str)
