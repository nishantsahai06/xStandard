"""Unit tests for ``schema_validator.validate_against_schema``.

Verifies that the schema-driven structural validator:
  • Produces zero issues for schema-valid modules.
  • Catches missing required properties.
  • Catches regex-pattern violations on DM code segments.
  • Catches mode/content conditional mismatches (allOf/if-then).
  • Catches missing provenance fields.
  • Returns SCHEMA-000 if serialisation itself fails.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.schema_validator import (
    validate_against_schema,
)
from fault_mapper.domain.enums import (
    FaultEntryType,
    FaultMode,
    ValidationSeverity,
)
from fault_mapper.domain.models import (
    FaultContent,
    FaultDescription,
    FaultEntry,
    FaultIsolationContent,
    FaultReportingContent,
    IsolationStep,
    Provenance,
    S1000DFaultDataModule,
)

from tests.fixtures.validation_fixtures import (
    make_module_bad_patterns,
    make_module_missing_header,
    make_module_missing_provenance,
    make_module_mode_content_mismatch,
    make_valid_dm_code,
    make_valid_fault_isolation_module,
    make_valid_fault_reporting_module,
    make_valid_header,
)


# ═══════════════════════════════════════════════════════════════════════
#  HAPPY PATH — zero issues
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaValidHappyPath:
    """Schema-valid modules produce zero issues."""

    def test_valid_reporting_module(self) -> None:
        issues = validate_against_schema(make_valid_fault_reporting_module())
        assert issues == []

    def test_valid_isolation_module(self) -> None:
        issues = validate_against_schema(make_valid_fault_isolation_module())
        assert issues == []

    def test_reporting_with_optional_fields(self) -> None:
        """Extra optional fields (classification, mapping_version) still pass."""
        from fault_mapper.domain.models import Classification
        from fault_mapper.domain.enums import ClassificationMethod
        module = make_valid_fault_reporting_module(
            mapping_version="2.0.0",
            classification=Classification(
                domain="S1000D", confidence=0.9, method=ClassificationMethod.RULES,
            ),
        )
        issues = validate_against_schema(module)
        assert issues == []


# ═══════════════════════════════════════════════════════════════════════
#  MISSING REQUIRED PROPERTIES
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaMissingRequired:
    """Missing required fields produce SCHEMA-* errors."""

    def test_missing_header(self) -> None:
        module = make_module_missing_header()
        issues = validate_against_schema(module)
        assert len(issues) >= 1
        codes = {i.code for i in issues}
        assert any(c.startswith("SCHEMA-") for c in codes)
        # All issues should be errors
        assert all(i.severity is ValidationSeverity.ERROR for i in issues)

    def test_missing_provenance(self) -> None:
        """Module without provenance misses sourceDocumentId + sourceSectionIds."""
        module = make_module_missing_provenance()
        issues = validate_against_schema(module)
        assert len(issues) >= 1
        # Check at least one issue mentions sourceDocumentId
        messages = " ".join(i.message for i in issues)
        assert "sourceDocumentId" in messages or "required" in messages.lower()

    def test_all_issues_are_errors(self) -> None:
        """Every schema violation is severity ERROR."""
        issues = validate_against_schema(make_module_missing_header())
        for issue in issues:
            assert issue.severity is ValidationSeverity.ERROR


# ═══════════════════════════════════════════════════════════════════════
#  PATTERN VIOLATIONS
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaPatternViolations:
    """DM code segments that violate regex patterns."""

    def test_bad_patterns_produce_errors(self) -> None:
        module = make_module_bad_patterns()
        issues = validate_against_schema(module)
        assert len(issues) >= 1
        # Should find pattern violations for sub_system_code, sub_sub_system_code, disassy_code
        codes = {i.code for i in issues}
        assert all(c.startswith("SCHEMA-") for c in codes)

    def test_bad_sub_system_code(self) -> None:
        """sub_system_code='00' (2 chars) violates ^[A-Z0-9]{1}$."""
        module = make_valid_fault_reporting_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(sub_system_code="00"),
            ),
        )
        issues = validate_against_schema(module)
        pattern_issues = [i for i in issues if "pattern" in i.message.lower()]
        assert len(pattern_issues) >= 1

    def test_bad_disassy_code(self) -> None:
        """disassy_code='A' (1 char) violates ^[A-Z0-9]{2}$."""
        module = make_valid_fault_reporting_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(disassy_code="A"),
            ),
        )
        issues = validate_against_schema(module)
        pattern_issues = [i for i in issues if "pattern" in i.message.lower()]
        assert len(pattern_issues) >= 1

    def test_lowercase_fails_pattern(self) -> None:
        """Lowercase letters violate the uppercase A-Z patterns."""
        module = make_valid_fault_reporting_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(sub_sub_system_code="a"),
            ),
        )
        issues = validate_against_schema(module)
        assert len(issues) >= 1

    def test_info_code_too_short(self) -> None:
        """info_code='03' (2 chars) violates ^[A-Z0-9]{3}$."""
        module = make_valid_fault_reporting_module(
            header=make_valid_header(
                dm_code=make_valid_dm_code(info_code="03"),
            ),
        )
        issues = validate_against_schema(module)
        assert len(issues) >= 1


# ═══════════════════════════════════════════════════════════════════════
#  MODE/CONTENT CONDITIONAL MISMATCH
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaModeMismatch:
    """allOf/if-then — mode says isolation but content has reporting."""

    def test_mode_content_mismatch_produces_errors(self) -> None:
        module = make_module_mode_content_mismatch()
        issues = validate_against_schema(module)
        assert len(issues) >= 1
        # At least one issue should relate to missing faultIsolation
        all_text = " ".join(i.message for i in issues)
        assert ("faultIsolation" in all_text
                or "required" in all_text.lower()
                or "anyOf" in all_text
                or "does not match" in all_text.lower())


# ═══════════════════════════════════════════════════════════════════════
#  SERIALISATION FAILURE → SCHEMA-000
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaSerialiseFailure:
    """If serialize_module raises, we get a SCHEMA-000 error."""

    def test_schema_000_on_serialise_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Monkeypatch serialize_module to raise, verify SCHEMA-000."""
        import fault_mapper.adapters.secondary.schema_validator as sv
        monkeypatch.setattr(sv, "serialize_module", lambda m: (_ for _ in ()).throw(RuntimeError("boom")))

        module = make_valid_fault_reporting_module()
        issues = validate_against_schema(module)
        assert len(issues) == 1
        assert issues[0].code == "SCHEMA-000"
        assert issues[0].severity is ValidationSeverity.ERROR
        assert "boom" in issues[0].message or "Serialisation" in issues[0].message


# ═══════════════════════════════════════════════════════════════════════
#  ISSUE STRUCTURE
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaIssueStructure:
    """Validate the shape of returned ValidationIssue objects."""

    def test_issues_have_field_path(self) -> None:
        issues = validate_against_schema(make_module_bad_patterns())
        for issue in issues:
            assert issue.field_path is not None

    def test_issues_have_context(self) -> None:
        issues = validate_against_schema(make_module_bad_patterns())
        for issue in issues:
            assert issue.context is not None

    def test_codes_are_sequential(self) -> None:
        """SCHEMA-001, SCHEMA-002, … with no gaps."""
        issues = validate_against_schema(make_module_bad_patterns())
        for idx, issue in enumerate(issues, start=1):
            assert issue.code == f"SCHEMA-{idx:03d}"
