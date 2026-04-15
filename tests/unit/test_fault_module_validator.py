"""Unit tests for ``FaultModuleValidator`` orchestrator.

Tests the orchestrator with stub callables (not real adapters),
verifying:
  • Correct delegation to structural, business, and review-gate callables.
  • ``_compute_result`` status logic.
  • ``_build_validation_results`` outcome mapping.
  • Module mutation (validation_status, review_status, validation_results).
"""

from __future__ import annotations

import pytest
from typing import Callable

from fault_mapper.application.fault_module_validator import FaultModuleValidator
from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationOutcome,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.models import S1000DFaultDataModule
from fault_mapper.domain.value_objects import (
    ModuleValidationResult,
    ReviewDecision,
    ValidationIssue,
)

from tests.fixtures.validation_fixtures import (
    make_valid_fault_reporting_module,
    make_validation_issue,
)


# ═══════════════════════════════════════════════════════════════════════
#  STUB FACTORIES
# ═══════════════════════════════════════════════════════════════════════


def _stub_structural(issues: list[ValidationIssue] | None = None):
    """Return a structural validator stub that returns fixed issues."""
    _issues = issues or []
    def validator(module: S1000DFaultDataModule) -> list[ValidationIssue]:
        return list(_issues)
    return validator


def _stub_business(issues: list[ValidationIssue] | None = None):
    """Return a business validator stub that returns fixed issues."""
    _issues = issues or []
    def validator(module: S1000DFaultDataModule) -> list[ValidationIssue]:
        return list(_issues)
    return validator


def _stub_gate(
    review_status: ReviewStatus = ReviewStatus.APPROVED,
    validation_status: ValidationStatus = ValidationStatus.APPROVED,
    auto_approved: bool = True,
):
    """Return a review-gate stub that returns a fixed decision."""
    def gate(
        module: S1000DFaultDataModule,
        result: ModuleValidationResult,
    ) -> ReviewDecision:
        return ReviewDecision(
            review_status=review_status,
            validation_status=validation_status,
            auto_approved=auto_approved,
            reasons=["stub"],
        )
    return gate


def _make_validator(
    structural_issues: list[ValidationIssue] | None = None,
    business_issues: list[ValidationIssue] | None = None,
    gate_review: ReviewStatus = ReviewStatus.APPROVED,
    gate_validation: ValidationStatus = ValidationStatus.APPROVED,
    gate_auto: bool = True,
) -> FaultModuleValidator:
    """Convenience: wire up a FaultModuleValidator with stubs."""
    return FaultModuleValidator(
        structural_validator=_stub_structural(structural_issues),
        business_validator=_stub_business(business_issues),
        review_gate=_stub_gate(gate_review, gate_validation, gate_auto),
    )


# ═══════════════════════════════════════════════════════════════════════
#  DELEGATION
# ═══════════════════════════════════════════════════════════════════════


class TestValidatorDelegation:
    """Verify the orchestrator calls all three injected callables."""

    def test_structural_called(self) -> None:
        called = []
        def structural(m):
            called.append("structural")
            return []
        validator = FaultModuleValidator(
            structural_validator=structural,
            business_validator=_stub_business(),
            review_gate=_stub_gate(),
        )
        module = make_valid_fault_reporting_module()
        validator.validate(module)
        assert "structural" in called

    def test_business_called(self) -> None:
        called = []
        def business(m):
            called.append("business")
            return []
        validator = FaultModuleValidator(
            structural_validator=_stub_structural(),
            business_validator=business,
            review_gate=_stub_gate(),
        )
        module = make_valid_fault_reporting_module()
        validator.validate(module)
        assert "business" in called

    def test_gate_called(self) -> None:
        called = []
        def gate(m, r):
            called.append("gate")
            return ReviewDecision(
                review_status=ReviewStatus.APPROVED,
                validation_status=ValidationStatus.APPROVED,
                auto_approved=True,
            )
        validator = FaultModuleValidator(
            structural_validator=_stub_structural(),
            business_validator=_stub_business(),
            review_gate=gate,
        )
        module = make_valid_fault_reporting_module()
        validator.validate(module)
        assert "gate" in called


# ═══════════════════════════════════════════════════════════════════════
#  STATUS COMPUTATION (_compute_result)
# ═══════════════════════════════════════════════════════════════════════


class TestComputeResult:
    """Verify the status derived from structural + business issues."""

    def test_clean_approved(self) -> None:
        validator = _make_validator()
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)
        assert result.status is ValidationStatus.APPROVED

    def test_structural_error_schema_failed(self) -> None:
        validator = _make_validator(
            structural_issues=[
                make_validation_issue(code="SCHEMA-001", severity=ValidationSeverity.ERROR),
            ],
            gate_review=ReviewStatus.REJECTED,
            gate_validation=ValidationStatus.SCHEMA_FAILED,
            gate_auto=False,
        )
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)
        assert result.status is ValidationStatus.SCHEMA_FAILED

    def test_business_error_business_rule_failed(self) -> None:
        validator = _make_validator(
            business_issues=[
                make_validation_issue(code="BIZ-001", severity=ValidationSeverity.ERROR),
            ],
            gate_review=ReviewStatus.REJECTED,
            gate_validation=ValidationStatus.BUSINESS_RULE_FAILED,
            gate_auto=False,
        )
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)
        assert result.status is ValidationStatus.BUSINESS_RULE_FAILED

    def test_structural_error_trumps_business_error(self) -> None:
        """When both have errors, structural takes priority → SCHEMA_FAILED."""
        validator = _make_validator(
            structural_issues=[
                make_validation_issue(code="SCHEMA-001", severity=ValidationSeverity.ERROR),
            ],
            business_issues=[
                make_validation_issue(code="BIZ-001", severity=ValidationSeverity.ERROR),
            ],
            gate_review=ReviewStatus.REJECTED,
            gate_validation=ValidationStatus.SCHEMA_FAILED,
            gate_auto=False,
        )
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)
        assert result.status is ValidationStatus.SCHEMA_FAILED

    def test_warnings_only_review_required(self) -> None:
        validator = _make_validator(
            business_issues=[
                make_validation_issue(code="BIZ-004", severity=ValidationSeverity.WARNING),
            ],
            gate_review=ReviewStatus.APPROVED,
            gate_validation=ValidationStatus.REVIEW_REQUIRED,
            gate_auto=True,
        )
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)
        assert result.status is ValidationStatus.REVIEW_REQUIRED


# ═══════════════════════════════════════════════════════════════════════
#  MODULE MUTATION
# ═══════════════════════════════════════════════════════════════════════


class TestModuleMutation:
    """Verify the orchestrator mutates the module in-place."""

    def test_clean_module_approved(self) -> None:
        validator = _make_validator()
        module = make_valid_fault_reporting_module()
        assert module.validation_status is ValidationStatus.PENDING

        validator.validate(module)

        assert module.validation_status is ValidationStatus.APPROVED
        assert module.review_status is ReviewStatus.APPROVED

    def test_errored_module_rejected(self) -> None:
        validator = _make_validator(
            structural_issues=[
                make_validation_issue(code="SCHEMA-001", severity=ValidationSeverity.ERROR),
            ],
            gate_review=ReviewStatus.REJECTED,
            gate_validation=ValidationStatus.SCHEMA_FAILED,
            gate_auto=False,
        )
        module = make_valid_fault_reporting_module()
        validator.validate(module)

        assert module.validation_status is ValidationStatus.SCHEMA_FAILED
        assert module.review_status is ReviewStatus.REJECTED

    def test_validation_results_populated(self) -> None:
        validator = _make_validator()
        module = make_valid_fault_reporting_module()
        assert module.validation_results is None

        validator.validate(module)

        assert module.validation_results is not None
        assert module.validation_results.completeness is ValidationOutcome.PASSED


# ═══════════════════════════════════════════════════════════════════════
#  VALIDATION RESULTS MAPPING (_build_validation_results)
# ═══════════════════════════════════════════════════════════════════════


class TestBuildValidationResults:
    """Verify ValidationResults outcomes are correctly computed."""

    def test_no_issues_all_passed(self) -> None:
        validator = _make_validator()
        module = make_valid_fault_reporting_module()
        validator.validate(module)

        vr = module.validation_results
        # No structural issues → schema NOT_RUN
        assert vr.schema is ValidationOutcome.NOT_RUN
        # No business issues → business_rules NOT_RUN
        assert vr.business_rules is ValidationOutcome.NOT_RUN
        # No issues at all → completeness PASSED
        assert vr.completeness is ValidationOutcome.PASSED

    def test_structural_errors_schema_failed(self) -> None:
        validator = _make_validator(
            structural_issues=[
                make_validation_issue(code="SCHEMA-001", severity=ValidationSeverity.ERROR),
            ],
            gate_review=ReviewStatus.REJECTED,
            gate_validation=ValidationStatus.SCHEMA_FAILED,
        )
        module = make_valid_fault_reporting_module()
        validator.validate(module)

        vr = module.validation_results
        assert vr.schema is ValidationOutcome.FAILED
        assert vr.completeness is ValidationOutcome.FAILED

    def test_structural_warnings_schema_warning(self) -> None:
        validator = _make_validator(
            structural_issues=[
                make_validation_issue(code="SCHEMA-W01", severity=ValidationSeverity.WARNING),
            ],
            gate_validation=ValidationStatus.REVIEW_REQUIRED,
        )
        module = make_valid_fault_reporting_module()
        validator.validate(module)

        vr = module.validation_results
        assert vr.schema is ValidationOutcome.WARNING

    def test_business_errors_biz_failed(self) -> None:
        validator = _make_validator(
            business_issues=[
                make_validation_issue(code="BIZ-001", severity=ValidationSeverity.ERROR),
            ],
            gate_review=ReviewStatus.REJECTED,
            gate_validation=ValidationStatus.BUSINESS_RULE_FAILED,
        )
        module = make_valid_fault_reporting_module()
        validator.validate(module)

        vr = module.validation_results
        assert vr.business_rules is ValidationOutcome.FAILED

    def test_business_warnings_biz_warning(self) -> None:
        validator = _make_validator(
            business_issues=[
                make_validation_issue(code="BIZ-004", severity=ValidationSeverity.WARNING),
            ],
            gate_validation=ValidationStatus.REVIEW_REQUIRED,
        )
        module = make_valid_fault_reporting_module()
        validator.validate(module)

        vr = module.validation_results
        assert vr.business_rules is ValidationOutcome.WARNING
        assert vr.completeness is ValidationOutcome.WARNING

    def test_return_value_matches_module(self) -> None:
        """validate() returns the same result reflected on the module."""
        validator = _make_validator()
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)

        assert result.status is ValidationStatus.APPROVED
        assert module.validation_status is ValidationStatus.APPROVED


# ═══════════════════════════════════════════════════════════════════════
#  ISSUE AGGREGATION
# ═══════════════════════════════════════════════════════════════════════


class TestIssueAggregation:
    """Verify all_issues, error_count, warning_count on the result."""

    def test_all_issues_combines_both(self) -> None:
        s_issue = make_validation_issue(code="SCHEMA-001", severity=ValidationSeverity.ERROR)
        b_issue = make_validation_issue(code="BIZ-004", severity=ValidationSeverity.WARNING)
        validator = _make_validator(
            structural_issues=[s_issue],
            business_issues=[b_issue],
            gate_review=ReviewStatus.REJECTED,
            gate_validation=ValidationStatus.SCHEMA_FAILED,
        )
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)

        assert len(result.all_issues) == 2
        assert result.error_count == 1
        assert result.warning_count == 1
        assert result.has_errors is True
        assert result.has_warnings is True

    def test_empty_issues_clean(self) -> None:
        validator = _make_validator()
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)

        assert len(result.all_issues) == 0
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.has_errors is False
        assert result.has_warnings is False
