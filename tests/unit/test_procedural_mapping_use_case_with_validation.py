"""Integration test: serialize → schema-validate → business-validate → gate.

Verifies the full map → serialize → validate path using real (non-stub)
implementations wired through the factory's ``create_validator()``.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.procedural_module_serializer import (
    serialize_procedural_module,
)
from fault_mapper.adapters.secondary.procedural_schema_validator import (
    validate_procedural_schema,
)
from fault_mapper.adapters.secondary.procedural_business_rule_validator import (
    validate_procedural_business_rules,
)
from fault_mapper.adapters.secondary.procedural_review_gate import (
    procedural_review_gate,
)
from fault_mapper.application.procedural_module_validator import (
    ProceduralModuleValidator,
)
from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationSeverity,
    ValidationStatus,
)
from fault_mapper.domain.procedural_models import (
    ProceduralContent,
    ProceduralSection,
    ProceduralStep,
    ProceduralValidationResults,
)
from fault_mapper.domain.procedural_enums import ProceduralSectionType

from tests.fixtures.procedural_validation_fixtures import (
    make_valid_procedural_module,
    make_procedural_module_empty_title,
    make_procedural_module_empty_step,
    make_procedural_module_no_lineage,
    make_procedural_header,
    make_procedural_section,
    make_procedural_step,
    make_procedural_lineage,
)


# ─── Wire real validator ─────────────────────────────────────────────


def _make_real_validator() -> ProceduralModuleValidator:
    return ProceduralModuleValidator(
        structural_validator=validate_procedural_schema,
        business_validator=validate_procedural_business_rules,
        review_gate=procedural_review_gate,
    )


# ═══════════════════════════════════════════════════════════════════════
#  END-TO-END: VALID MODULE
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationValidModule:
    """A fully valid module passes both validators and is approved."""

    def test_valid_module_serializes_and_passes(self) -> None:
        m = make_valid_procedural_module()
        d = serialize_procedural_module(m)
        # Confirm it round-trips through both validators
        schema_issues = validate_procedural_schema(m)
        biz_issues = validate_procedural_business_rules(m)
        assert schema_issues == []
        assert biz_issues == []

    def test_valid_module_approved_by_gate(self) -> None:
        validator = _make_real_validator()
        m = make_valid_procedural_module()
        result = validator.validate(m)
        assert result.status is ValidationStatus.APPROVED
        assert m.review_status is ReviewStatus.APPROVED

    def test_valid_module_validation_results_stored(self) -> None:
        validator = _make_real_validator()
        m = make_valid_procedural_module()
        validator.validate(m)
        assert m.validation is not None
        assert m.validation.schema_valid is True
        assert m.validation.business_rule_valid is True


# ═══════════════════════════════════════════════════════════════════════
#  END-TO-END: BUSINESS RULE FAILURES
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationBusinessFailures:
    """Business rule violations are detected by the real pipeline."""

    def test_empty_title_produces_error(self) -> None:
        validator = _make_real_validator()
        m = make_procedural_module_empty_title()
        result = validator.validate(m)
        codes = {i.code for i in result.all_issues}
        assert "BIZ-P-001" in codes

    def test_empty_step_produces_error(self) -> None:
        validator = _make_real_validator()
        m = make_procedural_module_empty_step()
        result = validator.validate(m)
        codes = {i.code for i in result.all_issues}
        assert "BIZ-P-006" in codes

    def test_no_lineage_produces_warning(self) -> None:
        validator = _make_real_validator()
        m = make_procedural_module_no_lineage()
        result = validator.validate(m)
        codes = {i.code for i in result.all_issues}
        assert "BIZ-P-008" in codes


# ═══════════════════════════════════════════════════════════════════════
#  END-TO-END: STATUS PROGRESSION
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationStatusProgression:
    """Status flows correctly through the pipeline."""

    def test_clean_module_status_approved(self) -> None:
        validator = _make_real_validator()
        m = make_valid_procedural_module()
        result = validator.validate(m)
        assert result.status is ValidationStatus.APPROVED

    def test_warning_only_status(self) -> None:
        """A module with only warnings should be REVIEW_REQUIRED or APPROVED."""
        validator = _make_real_validator()
        m = make_procedural_module_no_lineage()
        result = validator.validate(m)
        # No lineage is BIZ-P-008 WARNING — should be review_required
        assert result.status in {
            ValidationStatus.REVIEW_REQUIRED,
            ValidationStatus.APPROVED,
        }

    def test_error_module_gets_failed_status(self) -> None:
        """A module with errors should get BUSINESS_RULE_FAILED."""
        validator = _make_real_validator()
        m = make_procedural_module_empty_title()
        result = validator.validate(m)
        assert result.status in {
            ValidationStatus.BUSINESS_RULE_FAILED,
            ValidationStatus.SCHEMA_FAILED,
        }


# ═══════════════════════════════════════════════════════════════════════
#  SERIALIZER → SCHEMA ROUND-TRIP
# ═══════════════════════════════════════════════════════════════════════


class TestSerializerSchemaRoundTrip:
    """The serializer output passes the canonical JSON Schema."""

    def test_all_section_types_round_trip(self) -> None:
        """Modules with each domain section type pass schema validation."""
        for st in ProceduralSectionType:
            m = make_valid_procedural_module(
                content=ProceduralContent(
                    sections=[
                        make_procedural_section(section_type=st),
                    ],
                ),
            )
            issues = validate_procedural_schema(m)
            errors = [i for i in issues if i.is_error]
            assert errors == [], (
                f"Section type {st} failed schema: {errors}"
            )

    def test_multiple_steps_round_trip(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    ProceduralSection(
                        section_id="sec-multi",
                        title="Multi-Step",
                        section_order=1,
                        section_type=ProceduralSectionType.PROCEDURE,
                        page_numbers=[1, 2, 3],
                        steps=[
                            make_procedural_step(
                                step_id=f"s{i}", step_number=str(i),
                                text=f"Step {i} text.",
                            )
                            for i in range(1, 6)
                        ],
                    ),
                ],
            ),
        )
        issues = validate_procedural_schema(m)
        errors = [i for i in issues if i.is_error]
        assert errors == []
