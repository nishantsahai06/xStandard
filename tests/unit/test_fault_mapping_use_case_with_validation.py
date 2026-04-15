"""Integration test — full mapping use case with validation step.

Wires the real validators (schema + business) and review gate into the
use-case pipeline, then verifies that Step 6 validation runs and
mutates the module correctly.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.business_rule_validator import (
    validate_business_rules,
)
from fault_mapper.adapters.secondary.review_gate import default_review_gate
from fault_mapper.adapters.secondary.schema_validator import (
    validate_against_schema,
)
from fault_mapper.application.fault_module_validator import FaultModuleValidator
from fault_mapper.domain.enums import (
    FaultEntryType,
    FaultMode,
    MappingStrategy,
    ReviewStatus,
    ValidationOutcome,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    Classification,
    FaultContent,
    FaultDescription,
    FaultEntry,
    FaultIsolationContent,
    FaultReportingContent,
    IsolationStep,
    Provenance,
    S1000DFaultDataModule,
)
from fault_mapper.domain.value_objects import (
    FieldOrigin,
    MappingTrace,
)

from tests.fixtures.validation_fixtures import (
    make_module_bad_patterns,
    make_module_biz_info_code_mismatch,
    make_module_biz_missing_fault_code,
    make_module_missing_header,
    make_module_missing_provenance,
    make_module_with_low_confidence_trace,
    make_trace_low_confidence_llm,
    make_valid_fault_isolation_module,
    make_valid_fault_reporting_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  FACTORY — wire real adapters
# ═══════════════════════════════════════════════════════════════════════


def _real_validator() -> FaultModuleValidator:
    """Wire the real structural, business, and gate callables."""
    return FaultModuleValidator(
        structural_validator=validate_against_schema,
        business_validator=validate_business_rules,
        review_gate=default_review_gate,
    )


# ═══════════════════════════════════════════════════════════════════════
#  HAPPY PATH — clean module end-to-end
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationHappyPath:
    """A valid module passes all checks → APPROVED."""

    def test_reporting_module_approved(self) -> None:
        validator = _real_validator()
        module = make_valid_fault_reporting_module()
        result = validator.validate(module)

        assert result.status is ValidationStatus.APPROVED
        assert result.has_errors is False
        assert result.has_warnings is False
        assert module.validation_status is ValidationStatus.APPROVED
        assert module.review_status is ReviewStatus.APPROVED

    def test_isolation_module_approved(self) -> None:
        validator = _real_validator()
        module = make_valid_fault_isolation_module()
        result = validator.validate(module)

        assert result.status is ValidationStatus.APPROVED
        assert module.validation_status is ValidationStatus.APPROVED

    def test_validation_results_populated(self) -> None:
        validator = _real_validator()
        module = make_valid_fault_reporting_module()
        validator.validate(module)

        vr = module.validation_results
        assert vr is not None
        assert vr.completeness is ValidationOutcome.PASSED


# ═══════════════════════════════════════════════════════════════════════
#  SCHEMA FAILURE PATH
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationSchemaFailure:
    """Schema violations → SCHEMA_FAILED + REJECTED."""

    def test_missing_header_rejected(self) -> None:
        validator = _real_validator()
        module = make_module_missing_header()
        result = validator.validate(module)

        assert result.status is ValidationStatus.SCHEMA_FAILED
        assert result.has_errors is True
        assert module.validation_status is ValidationStatus.SCHEMA_FAILED
        assert module.review_status is ReviewStatus.REJECTED

    def test_bad_patterns_rejected(self) -> None:
        validator = _real_validator()
        module = make_module_bad_patterns()
        result = validator.validate(module)

        assert result.status is ValidationStatus.SCHEMA_FAILED
        assert module.review_status is ReviewStatus.REJECTED

    def test_missing_provenance_rejected(self) -> None:
        validator = _real_validator()
        module = make_module_missing_provenance()
        result = validator.validate(module)

        assert result.has_errors is True
        assert module.review_status is ReviewStatus.REJECTED


# ═══════════════════════════════════════════════════════════════════════
#  BUSINESS-RULE WARNING PATH
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationBusinessWarnings:
    """Business-rule warnings → REVIEW_REQUIRED with auto-approval logic."""

    def test_missing_fault_code_warning(self) -> None:
        """BIZ-004 warning, no LLM trace → auto-approved."""
        validator = _real_validator()
        module = make_module_biz_missing_fault_code()
        result = validator.validate(module)

        assert result.has_warnings is True
        assert result.has_errors is False
        # No trace → no LLM concern → auto-approved
        assert module.review_status is ReviewStatus.APPROVED

    def test_info_code_mismatch_warning(self) -> None:
        """BIZ-003 warning — advisory only."""
        validator = _real_validator()
        module = make_module_biz_info_code_mismatch()
        result = validator.validate(module)

        biz003 = [i for i in result.all_issues if i.code == "BIZ-003"]
        assert len(biz003) >= 1


# ═══════════════════════════════════════════════════════════════════════
#  LOW-CONFIDENCE LLM PATH
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationLowConfidenceLlm:
    """Low LLM confidence → warnings + NOT_REVIEWED."""

    def test_low_confidence_needs_review(self) -> None:
        validator = _real_validator()
        module = make_module_with_low_confidence_trace()
        result = validator.validate(module)

        # BIZ-010 should fire
        biz010 = [i for i in result.all_issues if i.code == "BIZ-010"]
        assert len(biz010) >= 1

        # Module should be NOT_REVIEWED (needs human)
        assert module.review_status is ReviewStatus.NOT_REVIEWED


# ═══════════════════════════════════════════════════════════════════════
#  COMBINED SCHEMA + BUSINESS ISSUES
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationCombinedIssues:
    """Schema + business errors co-exist; structural error dominates status."""

    def test_schema_error_plus_biz_warning(self) -> None:
        """Schema error dominates → SCHEMA_FAILED even with BIZ warnings."""
        validator = _real_validator()
        # Bad patterns (schema errors) + info_code mismatch (biz warning)
        module = make_valid_fault_reporting_module(
            record_id="REC-COMBINED",
            header=make_valid_fault_reporting_module().header,
        )
        # Inject a bad DM code that violates schema
        from tests.fixtures.validation_fixtures import make_valid_header, make_valid_dm_code
        module.header = make_valid_header(
            dm_code=make_valid_dm_code(
                sub_system_code="00",   # schema violation
                info_code="032",        # BIZ-003 (isolation code in reporting mode)
            ),
        )
        result = validator.validate(module)

        # Structural error dominates
        assert result.status is ValidationStatus.SCHEMA_FAILED
        # But business issues still collected
        biz = [i for i in result.business_issues if i.code == "BIZ-003"]
        assert len(biz) >= 1


# ═══════════════════════════════════════════════════════════════════════
#  IDEMPOTENCY / RE-VALIDATION
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationIdempotency:
    """Running validation twice produces the same result."""

    def test_double_validate_idempotent(self) -> None:
        validator = _real_validator()
        module = make_valid_fault_reporting_module()

        result1 = validator.validate(module)
        result2 = validator.validate(module)

        assert result1.status == result2.status
        assert module.validation_status is ValidationStatus.APPROVED
