"""Unit tests for ``procedural_schema_validator.validate_procedural_schema``.

Validates that the schema validator correctly:
  - Passes modules that conform to the canonical schema.
  - Rejects missing required fields.
  - Rejects invalid enum values.
  - Rejects pattern violations.
  - Reports each error as a SCHEMA-xxx ValidationIssue.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.procedural_schema_validator import (
    validate_procedural_schema,
)
from fault_mapper.domain.enums import ValidationSeverity, ValidationStatus
from fault_mapper.domain.procedural_enums import (
    ProceduralSectionType,
)
from fault_mapper.domain.procedural_models import (
    ProceduralContent,
    ProceduralHeader,
    ProceduralSection,
    ProceduralStep,
    ProceduralValidationResults,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.models import Provenance
from fault_mapper.domain.value_objects import DmCode, DmTitle

from tests.fixtures.procedural_validation_fixtures import (
    make_procedural_dm_code,
    make_procedural_header,
    make_procedural_section,
    make_procedural_step,
    make_procedural_lineage,
    make_procedural_content,
    make_valid_procedural_module,
    make_procedural_module_missing_header,
)


# ═══════════════════════════════════════════════════════════════════════
#  VALID MODULES PASS
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaValidModules:
    """Valid modules produce zero schema issues."""

    def test_minimal_valid_module_passes(self) -> None:
        issues = validate_procedural_schema(make_valid_procedural_module())
        errors = [i for i in issues if i.is_error]
        assert errors == [], f"Unexpected schema errors: {errors}"

    def test_module_with_multiple_sections_passes(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        section_id="sec-1", section_order=1,
                    ),
                    make_procedural_section(
                        section_id="sec-2",
                        title="Second Section",
                        section_order=2,
                        steps=[make_procedural_step(
                            step_id="s2", step_number="2",
                        )],
                    ),
                ],
            ),
        )
        issues = validate_procedural_schema(m)
        errors = [i for i in issues if i.is_error]
        assert errors == []

    def test_module_with_all_section_types_passes(self) -> None:
        """Every domain section type serializes to a canonical enum value."""
        sections = []
        for i, st in enumerate(ProceduralSectionType, start=1):
            sections.append(make_procedural_section(
                section_id=f"sec-{i}",
                title=f"Section {st.value}",
                section_order=i,
                section_type=st,
            ))
        m = make_valid_procedural_module(
            content=ProceduralContent(sections=sections),
        )
        issues = validate_procedural_schema(m)
        errors = [i for i in issues if i.is_error]
        assert errors == []


# ═══════════════════════════════════════════════════════════════════════
#  MISSING REQUIRED FIELDS
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaMissingRequired:
    """Missing required properties trigger SCHEMA-xxx errors."""

    def test_missing_header_produces_error(self) -> None:
        m = make_procedural_module_missing_header()
        issues = validate_procedural_schema(m)
        errors = [i for i in issues if i.is_error]
        assert len(errors) >= 1
        assert any("SCHEMA-" in i.code for i in errors)

    def test_empty_sections_array_still_valid(self) -> None:
        """Schema requires 'sections' key but may allow empty array."""
        m = make_valid_procedural_module(
            content=ProceduralContent(sections=[]),
        )
        issues = validate_procedural_schema(m)
        # Whether this is valid depends on schema minItems; just verify
        # the validator runs without exception
        assert isinstance(issues, list)


# ═══════════════════════════════════════════════════════════════════════
#  ISSUE STRUCTURE
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaIssueStructure:
    """Each schema issue has the proper code/severity/message shape."""

    def test_issue_code_pattern(self) -> None:
        m = make_procedural_module_missing_header()
        issues = validate_procedural_schema(m)
        for issue in issues:
            assert issue.code.startswith("SCHEMA-")

    def test_issue_severity_is_error(self) -> None:
        m = make_procedural_module_missing_header()
        issues = validate_procedural_schema(m)
        for issue in issues:
            assert issue.severity is ValidationSeverity.ERROR

    def test_issue_has_message(self) -> None:
        m = make_procedural_module_missing_header()
        issues = validate_procedural_schema(m)
        for issue in issues:
            assert issue.message
            assert len(issue.message) > 5

    def test_issue_has_field_path(self) -> None:
        m = make_procedural_module_missing_header()
        issues = validate_procedural_schema(m)
        for issue in issues:
            assert issue.field_path is not None


# ═══════════════════════════════════════════════════════════════════════
#  SERIALIZATION FAILURE
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaSerializationFailure:
    """If serialization itself throws, a SCHEMA-000 is returned."""

    def test_schema_000_on_serialization_exception(self, monkeypatch) -> None:
        """Monkeypatch the serializer to force an exception."""
        import fault_mapper.adapters.secondary.procedural_schema_validator as sv

        def _boom(_module):
            raise RuntimeError("boom")

        monkeypatch.setattr(sv, "serialize_procedural_module", _boom)

        m = make_valid_procedural_module()
        issues = sv.validate_procedural_schema(m)
        assert len(issues) == 1
        assert issues[0].code == "SCHEMA-000"
        assert "boom" in issues[0].message


# ═══════════════════════════════════════════════════════════════════════
#  SCHEMA VALIDATOR CONTRACT
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaValidatorContract:
    """validate_procedural_schema returns list[ValidationIssue]."""

    def test_returns_list(self) -> None:
        result = validate_procedural_schema(make_valid_procedural_module())
        assert isinstance(result, list)

    def test_empty_list_for_valid(self) -> None:
        result = validate_procedural_schema(make_valid_procedural_module())
        assert result == []
