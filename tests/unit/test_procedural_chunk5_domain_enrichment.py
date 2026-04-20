"""Chunk 5 — Domain-enrichment tests.

Verifies that the new domain types (SecurityClassification enum,
ResponsiblePartnerCompany VO, DataOrigin VO, ProceduralConfidence VO,
SourceSectionRef VO) are correctly used throughout the hexagonal stack:
domain models, assembler, header builder, serializer, business rules.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.procedural_module_serializer import (
    serialize_procedural_module,
)
from fault_mapper.adapters.secondary.procedural_business_rule_validator import (
    validate_procedural_business_rules,
)
from fault_mapper.domain.enums import ReviewStatus
from fault_mapper.domain.models import Provenance
from fault_mapper.domain.procedural_enums import (
    SecurityClassification,
    ProceduralSectionType,
)
from fault_mapper.domain.procedural_models import (
    ProceduralHeader,
    ProceduralLineage,
)
from fault_mapper.domain.procedural_value_objects import (
    DataOrigin,
    ProceduralConfidence,
    ResponsiblePartnerCompany,
    SourceSectionRef,
)
from tests.fixtures.procedural_validation_fixtures import (
    make_procedural_header,
    make_procedural_lineage,
    make_valid_procedural_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  A. SecurityClassification enum
# ═══════════════════════════════════════════════════════════════════════


class TestSecurityClassificationEnum:
    """Domain enum for S1000D security classification."""

    def test_enum_values(self) -> None:
        assert SecurityClassification.UNCLASSIFIED.value == "01-unclassified"
        assert SecurityClassification.TOP_SECRET.value == "05-top-secret"

    def test_all_five_levels(self) -> None:
        assert len(SecurityClassification) == 5

    def test_header_defaults_to_unclassified(self) -> None:
        h = make_procedural_header()
        assert h.security_classification is SecurityClassification.UNCLASSIFIED

    def test_serializer_emits_enum_value(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                security_classification=SecurityClassification.RESTRICTED,
            ),
        )
        d = serialize_procedural_module(m)
        assert d["identAndStatusSection"]["securityClassification"] == \
            "02-restricted"

    def test_biz_p015_passes_for_enum(self) -> None:
        """SecurityClassification enum is always valid by construction."""
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                security_classification=SecurityClassification.SECRET,
            ),
        )
        issues = validate_procedural_business_rules(m)
        assert not any(i.code == "BIZ-P-015" for i in issues)


# ═══════════════════════════════════════════════════════════════════════
#  B. ResponsiblePartnerCompany VO
# ═══════════════════════════════════════════════════════════════════════


class TestResponsiblePartnerCompanyVO:
    """Frozen VO for S1000D partner identity."""

    def test_frozen(self) -> None:
        rpc = ResponsiblePartnerCompany(
            enterprise_code="ACME", enterprise_name="Acme Corp",
        )
        with pytest.raises(AttributeError):
            rpc.enterprise_code = "X"  # type: ignore[misc]

    def test_defaults(self) -> None:
        rpc = ResponsiblePartnerCompany()
        assert rpc.enterprise_code == "UNKNOWN"
        assert rpc.enterprise_name == "Unknown"

    def test_serializer_reads_vo(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                responsible_partner_company=ResponsiblePartnerCompany(
                    enterprise_code="ACME",
                    enterprise_name="Acme Aviation",
                ),
            ),
        )
        d = serialize_procedural_module(m)
        rpc = d["identAndStatusSection"]["responsiblePartnerCompany"]
        assert rpc["enterpriseCode"] == "ACME"
        assert rpc["enterpriseName"] == "Acme Aviation"


# ═══════════════════════════════════════════════════════════════════════
#  C. DataOrigin VO
# ═══════════════════════════════════════════════════════════════════════


class TestDataOriginVO:
    """Frozen VO for extraction provenance."""

    def test_frozen(self) -> None:
        do = DataOrigin()
        with pytest.raises(AttributeError):
            do.is_extracted = False  # type: ignore[misc]

    def test_defaults(self) -> None:
        do = DataOrigin()
        assert do.is_extracted is True
        assert do.is_human_reviewed is False

    def test_serializer_reads_vo(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                origin=DataOrigin(is_extracted=False, is_human_reviewed=True),
            ),
        )
        d = serialize_procedural_module(m)
        origin = d["identAndStatusSection"]["origin"]
        assert origin["isExtracted"] is False
        assert origin["isHumanReviewed"] is True

    def test_origin_decoupled_from_review_status(self) -> None:
        """DataOrigin VO is independent of review_status field."""
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                origin=DataOrigin(is_extracted=True, is_human_reviewed=False),
            ),
        )
        m.review_status = ReviewStatus.APPROVED
        d = serialize_procedural_module(m)
        # Origin reads from VO, NOT from review_status
        assert d["identAndStatusSection"]["origin"]["isHumanReviewed"] is False


# ═══════════════════════════════════════════════════════════════════════
#  D. ProceduralConfidence VO
# ═══════════════════════════════════════════════════════════════════════


class TestProceduralConfidenceVO:
    """Multi-dimensional confidence for lineage."""

    def test_frozen(self) -> None:
        pc = ProceduralConfidence()
        with pytest.raises(AttributeError):
            pc.step_segmentation = 0.5  # type: ignore[misc]

    def test_average(self) -> None:
        pc = ProceduralConfidence(
            document_classification=1.0,
            dm_code_inference=0.8,
            section_typing=0.6,
            step_segmentation=0.4,
        )
        assert pc.average == pytest.approx(0.7)

    def test_serializer_emits_four_dimensions(self) -> None:
        m = make_valid_procedural_module(
            lineage=make_procedural_lineage(
                confidence=ProceduralConfidence(
                    document_classification=0.9,
                    dm_code_inference=0.8,
                    section_typing=0.7,
                    step_segmentation=0.6,
                ),
            ),
        )
        d = serialize_procedural_module(m)
        conf = d["lineage"]["confidence"]
        assert conf["documentClassification"] == pytest.approx(0.9)
        assert conf["dmCodeInference"] == pytest.approx(0.8)
        assert conf["sectionTyping"] == pytest.approx(0.7)
        assert conf["stepSegmentation"] == pytest.approx(0.6)


# ═══════════════════════════════════════════════════════════════════════
#  E. SourceSectionRef VO
# ═══════════════════════════════════════════════════════════════════════


class TestSourceSectionRefVO:
    """Structured lineage source-section reference."""

    def test_frozen(self) -> None:
        ref = SourceSectionRef(section_id="sec-1", page_numbers=(1, 2))
        with pytest.raises(AttributeError):
            ref.section_id = "other"  # type: ignore[misc]

    def test_serializer_emits_section_id(self) -> None:
        m = make_valid_procedural_module(
            lineage=make_procedural_lineage(
                source_sections=[
                    SourceSectionRef(section_id="sec-A"),
                    SourceSectionRef(section_id="sec-B", page_numbers=(3, 4)),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        ss = d["lineage"]["sourceSections"]
        assert len(ss) == 2
        assert ss[0]["sectionId"] == "sec-A"
        assert ss[1]["sectionId"] == "sec-B"


# ═══════════════════════════════════════════════════════════════════════
#  F. Provenance file metadata enrichment
# ═══════════════════════════════════════════════════════════════════════


class TestProvenanceFileMetadata:
    """Provenance carries file_name, file_type, source_path from source."""

    def test_serializer_reads_enriched_provenance(self) -> None:
        m = make_valid_procedural_module(
            source=Provenance(
                source_document_id="doc_test-enrich",
                file_name="manual.pdf",
                file_type="pdf",
                source_path="/uploads/manual.pdf",
            ),
        )
        d = serialize_procedural_module(m)
        src = d["source"]
        assert src["fileName"] == "manual.pdf"
        assert src["fileType"] == "pdf"
        assert src["sourcePath"] == "/uploads/manual.pdf"

    def test_serializer_falls_back_when_none(self) -> None:
        m = make_valid_procedural_module(
            source=Provenance(source_document_id="doc_fallback"),
        )
        d = serialize_procedural_module(m)
        src = d["source"]
        assert src["fileName"] == "unknown.pdf"
        assert src["fileType"] == "pdf"
        assert src["sourcePath"] == "/unknown"


# ═══════════════════════════════════════════════════════════════════════
#  G. Search projection fullText
# ═══════════════════════════════════════════════════════════════════════


class TestSearchProjectionFullText:
    """Serializer aggregates step text into fullText."""

    def test_full_text_includes_step_text(self) -> None:
        m = make_valid_procedural_module()
        d = serialize_procedural_module(m)
        ft = d["searchProjection"]["fullText"]
        assert "Remove the oil drain plug" in ft

    def test_full_text_includes_section_title(self) -> None:
        m = make_valid_procedural_module()
        d = serialize_procedural_module(m)
        ft = d["searchProjection"]["fullText"]
        assert "Oil Drain Procedure" in ft

    def test_full_text_empty_when_no_steps(self) -> None:
        from fault_mapper.domain.procedural_models import (
            ProceduralContent,
            ProceduralSection,
        )
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    ProceduralSection(
                        section_id="s1",
                        section_order=1,
                        section_type=ProceduralSectionType.PROCEDURE,
                        page_numbers=[1],
                        steps=[],
                        sub_sections=[],
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["searchProjection"]["fullText"] == ""


# ═══════════════════════════════════════════════════════════════════════
#  H. End-to-end schema validation with enriched domain
# ═══════════════════════════════════════════════════════════════════════


class TestChunk5SchemaValidation:
    """Enriched domain modules still pass canonical schema validation."""

    def test_enriched_module_passes_schema(self) -> None:
        from fault_mapper.adapters.secondary.procedural_schema_validator import (
            validate_procedural_schema,
        )
        m = make_valid_procedural_module(
            source=Provenance(
                source_document_id="doc_schema-test",
                file_name="engine_manual.pdf",
                file_type="pdf",
                source_path="/docs/engine_manual.pdf",
            ),
            ident_and_status_section=make_procedural_header(
                security_classification=SecurityClassification.CONFIDENTIAL,
                responsible_partner_company=ResponsiblePartnerCompany(
                    enterprise_code="BOEING",
                    enterprise_name="Boeing Commercial",
                ),
                origin=DataOrigin(is_extracted=True, is_human_reviewed=True),
            ),
            lineage=make_procedural_lineage(
                confidence=ProceduralConfidence(
                    document_classification=0.95,
                    dm_code_inference=0.88,
                    section_typing=0.92,
                    step_segmentation=0.85,
                ),
                source_sections=[
                    SourceSectionRef(section_id="sec-1", page_numbers=(1, 2)),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        issues = validate_procedural_schema(m)
        errors = [i for i in issues if i.severity.value == "error"]
        assert len(errors) == 0, f"Schema errors: {errors}"
