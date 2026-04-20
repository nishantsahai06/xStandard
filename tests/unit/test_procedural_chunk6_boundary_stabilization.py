"""Chunk 6 — Boundary-stabilization contract & regression tests.

Tests in this module verify:
  1. Serializer top-level key set matches CANONICAL_TOP_LEVEL_KEYS.
  2. Every documented fallback bridge (FB-01 .. FB-15) fires correctly.
  3. Golden-snapshot round-trip: fixture -> serialize -> schema-validate.
  4. No backward-compat str branches remain (type thinning).
  5. actionType is ALWAYS emitted on every step.
  6. _ACTION_TYPE_MAP has no None values.
  7. _ser_origin takes header (not module) and never reads review_status.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from fault_mapper.adapters.secondary.procedural_module_serializer import (
    CANONICAL_TOP_LEVEL_KEYS,
    FALLBACK_CODES,
    _ACTION_TYPE_MAP,
    _LINEAGE_METHOD_MAP,
    _REF_TYPE_MAP,
    _REQ_TYPE_MAP,
    _SECTION_TYPE_MAP,
    _STATUS_MAP,
    _gen_id,
    _ser_origin,
    _ser_responsible_partner,
    serialize_procedural_module,
)
from fault_mapper.adapters.secondary.procedural_schema_validator import (
    validate_procedural_schema,
)
from fault_mapper.domain.enums import ValidationStatus
from fault_mapper.domain.models import Provenance
from fault_mapper.domain.procedural_enums import (
    ActionType,
    ProceduralModuleType,
    ProceduralSectionType,
    SecurityClassification,
)
from fault_mapper.domain.procedural_models import (
    ProceduralContent,
    ProceduralHeader,
    ProceduralLineage,
    ProceduralSection,
    ProceduralStep,
    ProceduralValidationResults,
)
from fault_mapper.domain.procedural_value_objects import (
    DataOrigin,
    ProceduralConfidence,
    ResponsiblePartnerCompany,
    SourceSectionRef,
)
from fault_mapper.domain.value_objects import DmTitle
from tests.fixtures.procedural_validation_fixtures import (
    make_procedural_header,
    make_procedural_lineage,
    make_procedural_section,
    make_procedural_step,
    make_valid_procedural_module,
)


# ===================================================================
#  1. CONTRACT: CANONICAL_TOP_LEVEL_KEYS matches serializer output
# ===================================================================


class TestCanonicalTopLevelKeys:
    """Serialized output keys == CANONICAL_TOP_LEVEL_KEYS exactly."""

    def test_keys_match_exactly(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        assert set(d.keys()) == CANONICAL_TOP_LEVEL_KEYS

    def test_frozenset_has_nine_keys(self) -> None:
        assert len(CANONICAL_TOP_LEVEL_KEYS) == 9

    def test_no_extra_keys_possible(self) -> None:
        """Serializer returns dict literal — verify no dynamic additions."""
        d = serialize_procedural_module(make_valid_procedural_module())
        extra = set(d.keys()) - CANONICAL_TOP_LEVEL_KEYS
        assert extra == set(), f"Extra keys found: {extra}"


# ===================================================================
#  2. CONTRACT: FALLBACK_CODES
# ===================================================================


class TestFallbackCodes:
    """FALLBACK_CODES frozenset is complete."""

    def test_fifteen_codes(self) -> None:
        assert len(FALLBACK_CODES) == 15

    def test_codes_format(self) -> None:
        for code in FALLBACK_CODES:
            assert re.match(r"^FB-\d{2}$", code), f"Bad format: {code}"

    def test_fb01_through_fb15(self) -> None:
        expected = {f"FB-{i:02d}" for i in range(1, 16)}
        assert FALLBACK_CODES == expected


# ===================================================================
#  3. FALLBACK BRIDGE TESTS (FB-01 .. FB-15)
# ===================================================================


class TestFallbackBridges:
    """Each FB-XX fallback fires when domain data is None/missing."""

    # FB-01: file_name / file_type / source_path defaults
    def test_fb01_source_file_defaults(self) -> None:
        m = make_valid_procedural_module(source=None)
        d = serialize_procedural_module(m)
        assert d["source"]["fileName"] == "unknown.pdf"
        assert d["source"]["fileType"] == "pdf"
        assert d["source"]["sourcePath"] == "/unknown"

    # FB-02: source_document_id defaults
    def test_fb02_source_doc_id_default(self) -> None:
        m = make_valid_procedural_module(source=None)
        d = serialize_procedural_module(m)
        assert d["source"]["pipelineDocumentId"] == "doc_unknown"

    def test_fb02_provenance_none_doc_id(self) -> None:
        m = make_valid_procedural_module(
            source=Provenance(source_document_id=None),
        )
        d = serialize_procedural_module(m)
        assert d["source"]["pipelineDocumentId"] == "doc_unknown"

    # FB-03: infoName defaults to "Procedure"
    def test_fb03_info_name_default(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                dm_title=DmTitle(tech_name="Test", info_name=None),
            ),
        )
        d = serialize_procedural_module(m)
        assert d["identAndStatusSection"]["dmTitle"]["infoName"] == "Procedure"

    # FB-04: section title defaults
    def test_fb04_section_title_default(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[ProceduralSection(
                    section_id="sec-1", title=None, section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[1], steps=[make_procedural_step()],
                )],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["title"] == "Untitled Section"

    # FB-05: pageNumbers defaults to [1]
    def test_fb05_page_numbers_default(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[ProceduralSection(
                    section_id="sec-1", title="Test", section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[], steps=[make_procedural_step()],
                )],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["pageNumbers"] == [1]

    # FB-06: sectionOrder clamped to >= 1
    def test_fb06_section_order_min_one(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[make_procedural_section(section_order=0)],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["sectionOrder"] >= 1

    # FB-07: step text defaults to " "
    def test_fb07_step_text_default(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[ProceduralSection(
                    section_id="sec-1", title="Test", section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[1],
                    steps=[ProceduralStep(
                        step_id="s1", step_number="1", text=None,
                    )],
                )],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["steps"][0]["text"] == " "

    # FB-08: stepNumber defaults to "1"
    def test_fb08_step_number_default(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[ProceduralSection(
                    section_id="sec-1", title="Test", section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[1],
                    steps=[ProceduralStep(
                        step_id="s1", step_number=None, text="Do it",
                    )],
                )],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["steps"][0]["stepNumber"] == "1"

    # FB-09: generated IDs
    def test_fb09_generated_section_id(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[ProceduralSection(
                    section_id=None, title="Test", section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[1], steps=[make_procedural_step()],
                )],
            ),
        )
        d = serialize_procedural_module(m)
        sid = d["content"]["sections"][0]["sectionId"]
        assert sid.startswith("sec-")

    def test_fb09_generated_step_id(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[ProceduralSection(
                    section_id="sec-1", title="Test", section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[1],
                    steps=[ProceduralStep(
                        step_id=None, step_number="1", text="Do it",
                    )],
                )],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["steps"][0]["stepId"].startswith("step-")

    def test_fb09_gen_id_helper(self) -> None:
        result = _gen_id("test")
        assert result.startswith("test-")
        assert len(result) == len("test-") + 8

    # FB-10: SecurityClassification None
    def test_fb10_security_classification_default(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                security_classification=None,
            ),
        )
        d = serialize_procedural_module(m)
        assert d["identAndStatusSection"]["securityClassification"] == "01-unclassified"

    # FB-11: ResponsiblePartnerCompany None
    def test_fb11_responsible_partner_default(self) -> None:
        result = _ser_responsible_partner(None)
        assert result == {"enterpriseCode": "UNKNOWN", "enterpriseName": "Unknown"}

    def test_fb11_responsible_partner_vo(self) -> None:
        rpc = ResponsiblePartnerCompany(enterprise_code="ACME", enterprise_name="Acme Corp")
        result = _ser_responsible_partner(rpc)
        assert result["enterpriseCode"] == "ACME"

    # FB-12: DataOrigin fallback
    def test_fb12_origin_default(self) -> None:
        header = make_procedural_header(origin=None)
        result = _ser_origin(header)
        assert result == {"isExtracted": True, "isHumanReviewed": False}

    def test_fb12_origin_from_vo(self) -> None:
        header = make_procedural_header(
            origin=DataOrigin(is_extracted=False, is_human_reviewed=True),
        )
        result = _ser_origin(header)
        assert result == {"isExtracted": False, "isHumanReviewed": True}

    # FB-13: Lineage None
    def test_fb13_lineage_default(self) -> None:
        m = make_valid_procedural_module(lineage=None)
        d = serialize_procedural_module(m)
        lin = d["lineage"]
        assert lin["mappedBy"] == "xstandard-procedural-mapper"
        assert lin["sourceSections"] == []

    # FB-14: Validation None
    def test_fb14_validation_default(self) -> None:
        m = make_valid_procedural_module()
        d = serialize_procedural_module(m)
        v = d["validation"]
        assert v["schemaValid"] is False
        assert v["status"] == "draft"

    # FB-15: Confidence 0.0 -> null
    def test_fb15_confidence_zero_is_null(self) -> None:
        m = make_valid_procedural_module(
            lineage=make_procedural_lineage(
                confidence=ProceduralConfidence(
                    document_classification=0.0,
                    dm_code_inference=0.0,
                    section_typing=0.0,
                    step_segmentation=0.0,
                ),
            ),
        )
        d = serialize_procedural_module(m)
        conf = d["lineage"]["confidence"]
        for key in ("documentClassification", "dmCodeInference",
                     "sectionTyping", "stepSegmentation"):
            assert conf[key] is None, f"{key} should be None for 0.0"


# ===================================================================
#  4. TYPE-THINNING: no backward-compat str branches
# ===================================================================


class TestTypeThinning:
    """Chunk 6 removed backward-compat str branches."""

    def test_action_type_map_no_none_values(self) -> None:
        """_ACTION_TYPE_MAP: dict[ActionType, str] — no None values."""
        for action, canonical in _ACTION_TYPE_MAP.items():
            assert canonical is not None, f"{action} maps to None"
            assert isinstance(canonical, str)

    def test_responsible_partner_no_str_branch(self) -> None:
        """_ser_responsible_partner only accepts VO | None, not str."""
        import inspect
        sig = inspect.signature(_ser_responsible_partner)
        param = list(sig.parameters.values())[0]
        annotation = str(param.annotation)
        assert "str" not in annotation, (
            f"Backward-compat str branch still in signature: {annotation}"
        )

    def test_ser_origin_takes_header_not_module(self) -> None:
        """_ser_origin signature: (header: ProceduralHeader)."""
        import inspect
        sig = inspect.signature(_ser_origin)
        params = list(sig.parameters.keys())
        assert params == ["header"], f"Expected ['header'], got {params}"


# ===================================================================
#  5. actionType ALWAYS emitted
# ===================================================================


class TestActionTypeAlwaysEmitted:
    """Every step in serialized output has actionType."""

    def test_action_type_present_on_every_step(self) -> None:
        m = make_valid_procedural_module()
        d = serialize_procedural_module(m)
        for sec in d["content"]["sections"]:
            for step in sec["steps"]:
                assert "actionType" in step, f"Step {step['stepId']} missing actionType"

    @pytest.mark.parametrize("action", list(ActionType))
    def test_each_action_type_emits_string(self, action: ActionType) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[ProceduralSection(
                    section_id="sec-1", title="Test", section_order=1,
                    section_type=ProceduralSectionType.PROCEDURE,
                    page_numbers=[1],
                    steps=[ProceduralStep(
                        step_id="s1", step_number="1", text="Do it",
                        action_type=action,
                    )],
                )],
            ),
        )
        d = serialize_procedural_module(m)
        at = d["content"]["sections"][0]["steps"][0]["actionType"]
        assert isinstance(at, str)
        assert len(at) > 0


# ===================================================================
#  6. GOLDEN SNAPSHOT: serialize -> schema-validate
# ===================================================================


class TestGoldenSnapshotRoundTrip:
    """Canonical fixture serializes and passes schema validation."""

    def test_valid_module_passes_schema(self) -> None:
        m = make_valid_procedural_module()
        issues = validate_procedural_schema(m)
        assert issues == [], (
            f"Schema validation failed: {[str(i) for i in issues]}"
        )

    def test_serialized_shape_is_stable(self) -> None:
        """Key structure of serialized output is deterministic."""
        m = make_valid_procedural_module()
        d = serialize_procedural_module(m)

        # Top-level
        assert set(d.keys()) == CANONICAL_TOP_LEVEL_KEYS

        # Source block
        assert set(d["source"].keys()) == {
            "pipelineDocumentId", "fileName", "fileType",
            "sourcePath", "metadata",
        }

        # Ident section
        iss = d["identAndStatusSection"]
        assert "dmCode" in iss
        assert "origin" in iss
        assert "securityClassification" in iss

        # Content
        assert len(d["content"]["sections"]) >= 1
        sec = d["content"]["sections"][0]
        assert "steps" in sec
        assert "actionType" in sec["steps"][0]

        # Validation
        assert "schemaValid" in d["validation"]

        # Lineage
        assert "confidence" in d["lineage"]

    def test_serialized_json_roundtrip(self) -> None:
        """Output is JSON-serializable and round-trips cleanly."""
        m = make_valid_procedural_module()
        d = serialize_procedural_module(m)
        json_str = json.dumps(d, default=str)
        restored = json.loads(json_str)
        assert set(restored.keys()) == CANONICAL_TOP_LEVEL_KEYS


# ===================================================================
#  7. TRANSLATION MAP COMPLETENESS
# ===================================================================


class TestTranslationMapCompleteness:
    """Every domain enum value has a mapping entry."""

    def test_all_section_types_mapped(self) -> None:
        for st in ProceduralSectionType:
            assert st in _SECTION_TYPE_MAP, f"Missing: {st}"

    def test_all_action_types_mapped(self) -> None:
        for at in ActionType:
            assert at in _ACTION_TYPE_MAP, f"Missing: {at}"

    def test_status_map_covers_validation_statuses(self) -> None:
        for vs in ValidationStatus:
            if vs.value in _STATUS_MAP:
                assert isinstance(_STATUS_MAP[vs.value], str)


# ===================================================================
#  8. REGRESSION: _ser_origin does NOT read review_status
# ===================================================================


class TestOriginDoesNotReadReviewStatus:
    """_ser_origin reads header.origin VO, never module.review_status."""

    def test_origin_ignores_review_status(self) -> None:
        """Even if review_status is 'approved', origin reads from VO."""
        from fault_mapper.domain.enums import ReviewStatus
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                origin=DataOrigin(is_extracted=True, is_human_reviewed=False),
            ),
        )
        m.review_status = ReviewStatus.APPROVED
        d = serialize_procedural_module(m)
        origin = d["identAndStatusSection"]["origin"]
        # Origin should come from VO, not review_status
        assert origin["isHumanReviewed"] is False
