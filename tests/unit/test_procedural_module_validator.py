"""Unit tests for ``ProceduralModuleValidator`` orchestrator.

Tests that the validator:
  - Delegates to structural and business validators.
  - Computes aggregate status correctly.
  - Passes result to review gate.
  - Mutates the module in-place (review_status, validation).
"""

from __future__ import annotations

import pytest

from fault_mapper.application.procedural_module_validator import (
    ProceduralModuleValidator,
)
from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.procedural_models import (
    ProceduralValidationResults,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)

from tests.fixtures.procedural_validation_fixtures import (
    make_valid_procedural_module,
)


# ─── Stub validators ────────────────────────────────────────────────


def _no_issues(_module: S1000DProceduralDataModule) -> list[ValidationIssue]:
    return []


def _one_error(_module: S1000DProceduralDataModule) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            code="SCHEMA-001",
            severity=ValidationSeverity.ERROR,
            message="Mock schema error.",
        ),
    ]


def _one_warning(_module: S1000DProceduralDataModule) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            code="BIZ-P-002",
            severity=ValidationSeverity.WARNING,
            message="Mock business warning.",
        ),
    ]


def _approve_gate(
    _module: S1000DProceduralDataModule,
    result: ModuleValidationResult,
) -> ReviewDecision:
    return ReviewDecision(
        review_status=ReviewStatus.APPROVED,
        validation_status=result.status,
        reasons=["Approved by stub gate."],
        auto_approved=True,
    )


def _reject_gate(
    _module: S1000DProceduralDataModule,
    result: ModuleValidationResult,
) -> ReviewDecision:
    return ReviewDecision(
        review_status=ReviewStatus.REJECTED,
        validation_status=result.status,
        reasons=["Rejected by stub gate."],
        auto_approved=False,
    )


# ═══════════════════════════════════════════════════════════════════════
#  DELEGATION
# ═══════════════════════════════════════════════════════════════════════


class TestValidatorDelegation:
    """Validator calls structural, business, and gate in order."""

    def test_structural_called(self) -> None:
        calls = []

        def _spy(module):
            calls.append("structural")
            return []

        validator = ProceduralModuleValidator(
            structural_validator=_spy,
            business_validator=_no_issues,
            review_gate=_approve_gate,
        )
        validator.validate(make_valid_procedural_module())
        assert "structural" in calls

    def test_business_called(self) -> None:
        calls = []

        def _spy(module):
            calls.append("business")
            return []

        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_spy,
            review_gate=_approve_gate,
        )
        validator.validate(make_valid_procedural_module())
        assert "business" in calls

    def test_gate_called(self) -> None:
        calls = []

        def _spy(module, result):
            calls.append("gate")
            return _approve_gate(module, result)

        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_no_issues,
            review_gate=_spy,
        )
        validator.validate(make_valid_procedural_module())
        assert "gate" in calls


# ═══════════════════════════════════════════════════════════════════════
#  STATUS COMPUTATION
# ═══════════════════════════════════════════════════════════════════════


class TestValidatorStatusComputation:
    """Status derived from issue severity."""

    def test_clean_status_approved(self) -> None:
        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_no_issues,
            review_gate=_approve_gate,
        )
        result = validator.validate(make_valid_procedural_module())
        assert result.status is ValidationStatus.APPROVED

    def test_structural_error_schema_failed(self) -> None:
        validator = ProceduralModuleValidator(
            structural_validator=_one_error,
            business_validator=_no_issues,
            review_gate=_reject_gate,
        )
        result = validator.validate(make_valid_procedural_module())
        assert result.status is ValidationStatus.SCHEMA_FAILED

    def test_business_error_business_failed(self) -> None:
        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_one_error,
            review_gate=_reject_gate,
        )
        result = validator.validate(make_valid_procedural_module())
        assert result.status is ValidationStatus.BUSINESS_RULE_FAILED

    def test_warnings_only_review_required(self) -> None:
        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_one_warning,
            review_gate=_approve_gate,
        )
        result = validator.validate(make_valid_procedural_module())
        assert result.status is ValidationStatus.REVIEW_REQUIRED


# ═══════════════════════════════════════════════════════════════════════
#  MODULE MUTATION
# ═══════════════════════════════════════════════════════════════════════


class TestValidatorModuleMutation:
    """Validator mutates the module in-place."""

    def test_review_status_set(self) -> None:
        module = make_valid_procedural_module()
        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_no_issues,
            review_gate=_approve_gate,
        )
        validator.validate(module)
        assert module.review_status is ReviewStatus.APPROVED

    def test_validation_results_set(self) -> None:
        module = make_valid_procedural_module()
        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_no_issues,
            review_gate=_approve_gate,
        )
        validator.validate(module)
        assert module.validation is not None
        assert isinstance(module.validation, ProceduralValidationResults)

    def test_rejected_sets_review_status(self) -> None:
        module = make_valid_procedural_module()
        validator = ProceduralModuleValidator(
            structural_validator=_one_error,
            business_validator=_no_issues,
            review_gate=_reject_gate,
        )
        validator.validate(module)
        assert module.review_status is ReviewStatus.REJECTED

    def test_validation_errors_populated(self) -> None:
        module = make_valid_procedural_module()
        validator = ProceduralModuleValidator(
            structural_validator=_one_error,
            business_validator=_no_issues,
            review_gate=_reject_gate,
        )
        validator.validate(module)
        assert module.validation is not None
        assert len(module.validation.errors) >= 1

    def test_validation_schema_valid_flag(self) -> None:
        module = make_valid_procedural_module()
        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_no_issues,
            review_gate=_approve_gate,
        )
        validator.validate(module)
        assert module.validation.schema_valid is True

    def test_validation_business_valid_flag(self) -> None:
        module = make_valid_procedural_module()
        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_no_issues,
            review_gate=_approve_gate,
        )
        validator.validate(module)
        assert module.validation.business_rule_valid is True


# ═══════════════════════════════════════════════════════════════════════
#  RESULT STRUCTURE
# ═══════════════════════════════════════════════════════════════════════


class TestValidatorResultStructure:
    """ModuleValidationResult has proper shape."""

    def test_result_has_all_issues(self) -> None:
        validator = ProceduralModuleValidator(
            structural_validator=_one_error,
            business_validator=_one_warning,
            review_gate=_reject_gate,
        )
        result = validator.validate(make_valid_procedural_module())
        assert len(result.all_issues) == 2

    def test_result_error_count(self) -> None:
        validator = ProceduralModuleValidator(
            structural_validator=_one_error,
            business_validator=_no_issues,
            review_gate=_reject_gate,
        )
        result = validator.validate(make_valid_procedural_module())
        assert result.error_count == 1

    def test_result_warning_count(self) -> None:
        validator = ProceduralModuleValidator(
            structural_validator=_no_issues,
            business_validator=_one_warning,
            review_gate=_approve_gate,
        )
        result = validator.validate(make_valid_procedural_module())
        assert result.warning_count == 1
