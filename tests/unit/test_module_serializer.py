"""Unit tests for ``module_serializer.serialize_module``.

Verifies that the serialiser produces dicts whose shape, key names,
and value types match what the canonical JSON Schema expects.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.module_serializer import serialize_module
from fault_mapper.domain.enums import (
    FaultEntryType,
    FaultMode,
    ValidationOutcome,
    ValidationStatus,
)
from fault_mapper.domain.models import (
    Classification,
    CommonInfo,
    FaultContent,
    FaultDescription,
    FaultEntry,
    FaultIsolationContent,
    FaultReportingContent,
    IsolationStep,
    IsolationStepBranch,
    IsolationResult,
    Lru,
    Provenance,
    Ref,
    S1000DFaultDataModule,
    ValidationResults,
    XmlMeta,
)

from tests.fixtures.validation_fixtures import (
    make_valid_fault_isolation_module,
    make_valid_fault_reporting_module,
    make_valid_dm_code,
    make_valid_header,
)


# ═══════════════════════════════════════════════════════════════════════
#  TOP-LEVEL STRUCTURE
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeTopLevel:
    """The serialised dict has the correct top-level keys and types."""

    def test_required_keys_present(self) -> None:
        module = make_valid_fault_reporting_module()
        d = serialize_module(module)

        for key in ("recordId", "recordType", "mode", "validationStatus",
                     "sourceDocumentId", "sourceSectionIds", "header", "content"):
            assert key in d, f"Missing required top-level key: {key}"

    def test_record_type_constant(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        assert d["recordType"] == "S1000D_FaultDataModule"

    def test_mode_value_is_string(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        assert d["mode"] == "faultReporting"

    def test_validation_status_default(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        assert d["validationStatus"] == "pending"

    def test_provenance_flattened(self) -> None:
        module = make_valid_fault_reporting_module(
            provenance=Provenance(
                source_document_id="doc-X",
                source_section_ids=["s1", "s2"],
                source_pages=[1, 2, 3],
            ),
        )
        d = serialize_module(module)
        assert d["sourceDocumentId"] == "doc-X"
        assert d["sourceSectionIds"] == ["s1", "s2"]
        assert d["sourcePages"] == [1, 2, 3]

    def test_provenance_none_omits_keys(self) -> None:
        module = make_valid_fault_reporting_module(provenance=None)
        d = serialize_module(module)
        assert "sourceDocumentId" not in d
        assert "sourceSectionIds" not in d

    def test_source_pages_omitted_when_empty(self) -> None:
        module = make_valid_fault_reporting_module(
            provenance=Provenance(
                source_document_id="doc-1",
                source_section_ids=["s1"],
                source_pages=[],
            ),
        )
        d = serialize_module(module)
        assert "sourcePages" not in d

    def test_optional_mapping_version(self) -> None:
        module = make_valid_fault_reporting_module(mapping_version="1.2.3")
        d = serialize_module(module)
        assert d["mappingVersion"] == "1.2.3"

    def test_mapping_version_omitted_when_none(self) -> None:
        module = make_valid_fault_reporting_module(mapping_version=None)
        d = serialize_module(module)
        assert "mappingVersion" not in d


# ═══════════════════════════════════════════════════════════════════════
#  HEADER SERIALISATION
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeHeader:
    """Header section serialises DM code, language, issue info, etc."""

    def test_header_keys(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        header = d["header"]
        for key in ("dmCode", "language", "issueInfo", "issueDate", "dmTitle"):
            assert key in header, f"Missing header key: {key}"

    def test_dm_code_segments(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        dm = d["header"]["dmCode"]
        assert dm["modelIdentCode"] == "TESTAC"
        assert dm["subSystemCode"] == "0"
        assert dm["subSubSystemCode"] == "0"
        assert dm["disassyCode"] == "AA"
        assert dm["infoCode"] == "031"
        assert dm["itemLocationCode"] == "A"

    def test_language_keys(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        lang = d["header"]["language"]
        assert lang["languageIsoCode"] == "en"
        assert lang["countryIsoCode"] == "US"

    def test_dm_title_keys(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        title = d["header"]["dmTitle"]
        assert title["techName"] == "Fault Report"
        assert title["infoName"] == "Fault Reporting"

    def test_header_none_omits_key(self) -> None:
        module = make_valid_fault_reporting_module(header=None)
        d = serialize_module(module)
        assert "header" not in d


# ═══════════════════════════════════════════════════════════════════════
#  CONTENT SERIALISATION
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeContent:
    """Content section — faultReporting vs faultIsolation."""

    def test_reporting_content_shape(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        content = d["content"]
        assert "refs" in content
        assert "warningsAndCautions" in content
        assert "faultReporting" in content
        assert content["faultIsolation"] is None

    def test_isolation_content_shape(self) -> None:
        d = serialize_module(make_valid_fault_isolation_module())
        content = d["content"]
        assert "faultIsolation" in content
        assert content["faultReporting"] is None

    def test_fault_entry_serialisation(self) -> None:
        d = serialize_module(make_valid_fault_reporting_module())
        entries = d["content"]["faultReporting"]["faultEntries"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entryType"] == "detectedFault"
        assert entry["faultCode"] == "FC001"

    def test_isolation_step_serialisation(self) -> None:
        d = serialize_module(make_valid_fault_isolation_module())
        steps = d["content"]["faultIsolation"]["faultIsolationSteps"]
        assert len(steps) == 1
        step = steps[0]
        assert step["stepNumber"] == 1
        assert step["instruction"] == "Check power supply."

    def test_fault_entry_with_nulls_omits_optional(self) -> None:
        """Fault entry with None optional fields should omit them."""
        module = make_valid_fault_reporting_module(
            content=FaultContent(
                refs=[],
                warnings_and_cautions=[],
                fault_reporting=FaultReportingContent(
                    fault_entries=[
                        FaultEntry(
                            entry_type=FaultEntryType.DETECTED_FAULT,
                            fault_code="FC001",
                            fault_descr=FaultDescription(descr="Test"),
                            detection_info=None,
                            locate_and_repair=None,
                            remarks=None,
                        ),
                    ],
                ),
            ),
        )
        d = serialize_module(module)
        entry = d["content"]["faultReporting"]["faultEntries"][0]
        assert "detectionInfo" not in entry
        assert "locateAndRepair" not in entry
        assert "remarks" not in entry


# ═══════════════════════════════════════════════════════════════════════
#  OPTIONAL SECTIONS
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeOptionalSections:
    """Classification, validationResults, xmlMeta."""

    def test_classification_serialisation(self) -> None:
        from fault_mapper.domain.enums import ClassificationMethod
        module = make_valid_fault_reporting_module(
            classification=Classification(
                domain="S1000D", confidence=0.85, method=ClassificationMethod.RULES,
            ),
        )
        d = serialize_module(module)
        cls = d["classification"]
        assert cls["domain"] == "S1000D"
        assert cls["confidence"] == 0.85
        assert cls["method"] == "rules"

    def test_classification_omitted_when_none(self) -> None:
        module = make_valid_fault_reporting_module(classification=None)
        d = serialize_module(module)
        assert "classification" not in d

    def test_validation_results_serialisation(self) -> None:
        module = make_valid_fault_reporting_module(
            validation_results=ValidationResults(
                schema=ValidationOutcome.PASSED,
                completeness=ValidationOutcome.PASSED,
                business_rules=ValidationOutcome.WARNING,
            ),
        )
        d = serialize_module(module)
        vr = d["validationResults"]
        assert vr["schema"] == "passed"
        assert vr["businessRules"] == "warning"

    def test_xml_meta_serialisation(self) -> None:
        module = make_valid_fault_reporting_module(
            xml_meta=XmlMeta(id="xml-1", schema_source="s1000d_5.0"),
        )
        d = serialize_module(module)
        xm = d["xmlMeta"]
        assert xm["id"] == "xml-1"
        assert xm["schemaSource"] == "s1000d_5.0"

    def test_xml_meta_omitted_when_none(self) -> None:
        module = make_valid_fault_reporting_module(xml_meta=None)
        d = serialize_module(module)
        assert "xmlMeta" not in d


# ═══════════════════════════════════════════════════════════════════════
#  ROUND-TRIP PROPERTY
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeRoundTrip:
    """Serialise → validate against schema → zero SCHEMA-* issues."""

    def test_valid_reporting_round_trip(self) -> None:
        from fault_mapper.adapters.secondary.schema_validator import (
            validate_against_schema,
        )
        module = make_valid_fault_reporting_module()
        issues = validate_against_schema(module)
        assert issues == [], f"Unexpected issues: {issues}"

    def test_valid_isolation_round_trip(self) -> None:
        from fault_mapper.adapters.secondary.schema_validator import (
            validate_against_schema,
        )
        module = make_valid_fault_isolation_module()
        issues = validate_against_schema(module)
        assert issues == [], f"Unexpected issues: {issues}"
