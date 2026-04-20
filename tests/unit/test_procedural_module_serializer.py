"""Unit tests for ``procedural_module_serializer.serialize_procedural_module``.

Verifies the anti-corruption adapter produces dicts whose shape, key names,
and value types match the canonical procedural JSON Schema.
"""

from __future__ import annotations

import pytest

from fault_mapper.adapters.secondary.procedural_module_serializer import (
    serialize_procedural_module,
    _SECTION_TYPE_MAP,
    _ACTION_TYPE_MAP,
    _LINEAGE_METHOD_MAP,
    _REQ_TYPE_MAP,
    _REF_TYPE_MAP,
    _STATUS_MAP,
)
from fault_mapper.domain.enums import (
    ReviewStatus,
    ValidationStatus,
)
from fault_mapper.domain.enums import NoteLikeKind
from fault_mapper.domain.models import (
    FigureRef,
    NoteLike,
    Provenance,
)
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
    ProceduralReference,
    ProceduralRequirementItem,
    ProceduralSection,
    ProceduralStep,
    ProceduralTableRef,
    ProceduralValidationResults,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.procedural_value_objects import (
    DataOrigin,
    ProceduralConfidence,
    ResponsiblePartnerCompany,
    SourceSectionRef,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    IssueDate,
    IssueInfo,
    Language,
)
from tests.fixtures.procedural_validation_fixtures import (
    make_procedural_dm_code,
    make_procedural_header,
    make_procedural_section,
    make_procedural_step,
    make_procedural_lineage,
    make_procedural_content,
    make_valid_procedural_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  TOP-LEVEL STRUCTURE
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeTopLevel:
    """Serialized dict has canonical top-level keys."""

    def test_required_keys_present(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        for key in (
            "schemaVersion", "moduleType", "source",
            "identAndStatusSection", "content", "validation", "lineage",
        ):
            assert key in d, f"Missing required key: {key}"

    def test_optional_keys_present(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        assert "csdbRecordId" in d
        assert "searchProjection" in d

    def test_schema_version_string(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        assert d["schemaVersion"] == "1.0.0"

    def test_module_type_is_enum_value(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        assert d["moduleType"] == "procedural"

    def test_descriptive_module_type(self) -> None:
        m = make_valid_procedural_module(
            module_type=ProceduralModuleType.DESCRIPTIVE,
        )
        d = serialize_procedural_module(m)
        assert d["moduleType"] == "descriptive"

    def test_csdb_record_id(self) -> None:
        m = make_valid_procedural_module(record_id="PROC-XYZ")
        d = serialize_procedural_module(m)
        assert d["csdbRecordId"] == "PROC-XYZ"

    def test_no_extra_top_level_keys(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        canonical = {
            "schemaVersion", "moduleType", "csdbRecordId", "source",
            "identAndStatusSection", "content", "searchProjection",
            "validation", "lineage",
        }
        assert set(d.keys()) <= canonical


# ═══════════════════════════════════════════════════════════════════════
#  SOURCE
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeSource:
    """Provenance → canonical source block."""

    def test_pipeline_document_id_from_provenance(self) -> None:
        m = make_valid_procedural_module(
            source=Provenance(source_document_id="doc_abc-123"),
        )
        d = serialize_procedural_module(m)
        assert d["source"]["pipelineDocumentId"] == "doc_abc-123"

    def test_doc_prefix_added_if_missing(self) -> None:
        m = make_valid_procedural_module(
            source=Provenance(source_document_id="abc-123"),
        )
        d = serialize_procedural_module(m)
        assert d["source"]["pipelineDocumentId"] == "doc_abc-123"

    def test_none_source_defaults(self) -> None:
        m = make_valid_procedural_module(source=None)
        d = serialize_procedural_module(m)
        assert d["source"]["pipelineDocumentId"] == "doc_unknown"
        assert d["source"]["fileName"] == "unknown.pdf"

    def test_source_has_required_keys(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        src = d["source"]
        for key in ("pipelineDocumentId", "fileName", "fileType",
                     "sourcePath", "metadata"):
            assert key in src

    def test_source_metadata_shape(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        meta = d["source"]["metadata"]
        assert "pipelineVersion" in meta


# ═══════════════════════════════════════════════════════════════════════
#  IDENT AND STATUS SECTION
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeIdentAndStatus:
    """ProceduralHeader → canonical identAndStatusSection."""

    def test_all_canonical_keys_present(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        iss = d["identAndStatusSection"]
        for key in (
            "dmCode", "language", "issueInfo", "issueDate", "dmTitle",
            "securityClassification", "responsiblePartnerCompany", "origin",
        ):
            assert key in iss, f"Missing key: {key}"

    def test_dm_code_serialization(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        dc = d["identAndStatusSection"]["dmCode"]
        assert dc["modelIdentCode"] == "TESTAC"
        assert dc["systemCode"] == "29"
        assert "dmCodeString" in dc

    def test_dm_code_learn_code_null_when_none(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        dc = d["identAndStatusSection"]["dmCode"]
        assert dc["learnCode"] is None
        assert dc["learnEventCode"] is None

    def test_language_shape(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        lang = d["identAndStatusSection"]["language"]
        assert lang == {"languageIsoCode": "en", "countryIsoCode": "US"}

    def test_issue_info_shape(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        ii = d["identAndStatusSection"]["issueInfo"]
        assert ii == {"issueNumber": "001", "inWork": "00"}

    def test_issue_date_shape(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        dt = d["identAndStatusSection"]["issueDate"]
        assert dt == {"year": "2026", "month": "04", "day": "16"}

    def test_dm_title_shape(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        t = d["identAndStatusSection"]["dmTitle"]
        assert t["techName"] == "Maintenance Procedure"
        assert t["infoName"] == "Engine Oil Change"

    def test_dm_title_info_name_defaults_to_procedure(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                dm_title=DmTitle(tech_name="X", info_name=None),
            ),
        )
        d = serialize_procedural_module(m)
        assert d["identAndStatusSection"]["dmTitle"]["infoName"] == "Procedure"

    def test_security_classification_default(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                security_classification=None,
            ),
        )
        d = serialize_procedural_module(m)
        assert d["identAndStatusSection"]["securityClassification"] == \
            "01-unclassified"

    def test_responsible_partner_company_object(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        rpc = d["identAndStatusSection"]["responsiblePartnerCompany"]
        assert rpc["enterpriseCode"] == "LEXX"
        assert rpc["enterpriseName"] == "LEXX Aerospace"

    def test_responsible_partner_company_none_defaults(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                responsible_partner_company=None,
            ),
        )
        d = serialize_procedural_module(m)
        rpc = d["identAndStatusSection"]["responsiblePartnerCompany"]
        assert rpc["enterpriseCode"] == "UNKNOWN"

    def test_origin_object_shape(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        origin = d["identAndStatusSection"]["origin"]
        assert origin["isExtracted"] is True
        assert origin["isHumanReviewed"] is False  # NOT_REVIEWED default

    def test_origin_human_reviewed_when_approved(self) -> None:
        m = make_valid_procedural_module(
            ident_and_status_section=make_procedural_header(
                origin=DataOrigin(is_extracted=True, is_human_reviewed=True),
            ),
        )
        d = serialize_procedural_module(m)
        assert d["identAndStatusSection"]["origin"]["isHumanReviewed"] is True

    def test_none_header_emits_empty_dict(self) -> None:
        m = make_valid_procedural_module(ident_and_status_section=None)
        d = serialize_procedural_module(m)
        assert d["identAndStatusSection"] == {}


# ═══════════════════════════════════════════════════════════════════════
#  CONTENT / SECTIONS / STEPS
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeContent:
    """ProceduralContent → canonical content block."""

    def test_sections_is_list(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        assert isinstance(d["content"]["sections"], list)
        assert len(d["content"]["sections"]) >= 1

    def test_section_has_canonical_keys(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        sec = d["content"]["sections"][0]
        for key in ("sectionId", "title", "sectionOrder", "sectionType",
                     "pageNumbers", "steps"):
            assert key in sec, f"Missing section key: {key}"

    def test_section_type_mapped_from_domain(self) -> None:
        """PROCEDURE domain type → 'mainProcedure' canonical."""
        d = serialize_procedural_module(make_valid_procedural_module())
        assert d["content"]["sections"][0]["sectionType"] == "mainProcedure"

    def test_all_domain_section_types_map(self) -> None:
        """Every domain ProceduralSectionType has a canonical mapping."""
        for domain_type in ProceduralSectionType:
            assert domain_type in _SECTION_TYPE_MAP

    def test_page_numbers_defaults_to_one(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    ProceduralSection(
                        section_id="sec-empty-pages",
                        title="No Pages",
                        section_order=1,
                        section_type=ProceduralSectionType.PROCEDURE,
                        page_numbers=[],
                        steps=[make_procedural_step()],
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["pageNumbers"] == [1]

    def test_section_order_minimum_one(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(section_order=0),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["sectionOrder"] >= 1

    def test_section_title_defaults_to_untitled(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    ProceduralSection(
                        section_id="sec-no-title",
                        title=None,
                        section_order=1,
                        section_type=ProceduralSectionType.PROCEDURE,
                        page_numbers=[1],
                        steps=[make_procedural_step()],
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        assert d["content"]["sections"][0]["title"] == "Untitled Section"

    def test_step_has_canonical_keys(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        step = d["content"]["sections"][0]["steps"][0]
        for key in ("stepId", "stepNumber", "text"):
            assert key in step, f"Missing step key: {key}"

    def test_action_type_mapped(self) -> None:
        """REMOVE → 'remove'."""
        d = serialize_procedural_module(make_valid_procedural_module())
        step = d["content"]["sections"][0]["steps"][0]
        assert step.get("actionType") == "remove"

    def test_all_domain_action_types_map(self) -> None:
        """Every domain ActionType has a canonical mapping entry."""
        for action in ActionType:
            assert action in _ACTION_TYPE_MAP

    def test_sub_steps_not_emitted(self) -> None:
        """Canonical schema has no sub-steps in proceduralStep."""
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    ProceduralSection(
                        section_id="sec-1",
                        title="Test",
                        section_order=1,
                        section_type=ProceduralSectionType.PROCEDURE,
                        page_numbers=[1],
                        steps=[
                            ProceduralStep(
                                step_id="s1",
                                step_number="1",
                                text="Parent",
                                sub_steps=[
                                    ProceduralStep(
                                        step_id="s1a",
                                        step_number="1a",
                                        text="Child",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        step = d["content"]["sections"][0]["steps"][0]
        assert "subSteps" not in step
        assert "sub_steps" not in step


class TestSerializeContentExtras:
    """Preliminary requirements, notices, figures, tables, references."""

    def test_preliminary_requirements_serialized(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[make_procedural_section()],
                preliminary_requirements=[
                    ProceduralRequirementItem(
                        requirement_type="equipment",
                        name="Torque wrench",
                        ident_number="TW-001",
                        quantity=1.0,
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        reqs = d["content"]["preliminaryRequirements"]
        assert len(reqs) == 1
        assert reqs[0]["type"] == "tool"
        assert reqs[0]["text"] == "Torque wrench"

    def test_requirement_type_mapping(self) -> None:
        for domain, canonical in _REQ_TYPE_MAP.items():
            assert isinstance(canonical, str)

    def test_warnings_cautions_notes_serialized(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[make_procedural_section()],
                warnings=[NoteLike(kind=NoteLikeKind.WARNING, text="Be careful")],
                cautions=[NoteLike(kind=NoteLikeKind.CAUTION, text="Watch out")],
                notes=[NoteLike(kind=NoteLikeKind.NOTE, text="FYI")],
            ),
        )
        d = serialize_procedural_module(m)
        assert len(d["content"]["warnings"]) == 1
        assert len(d["content"]["cautions"]) == 1
        assert len(d["content"]["notes"]) == 1

    def test_figures_serialized(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        figures=[FigureRef(figure_id="fig-1", caption="Diagram")],
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        figs = d["content"]["sections"][0]["figures"]
        assert len(figs) == 1
        assert figs[0]["caption"] == "Diagram"

    def test_tables_serialized(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        tables=[ProceduralTableRef(
                            table_id="tbl-1", caption="Spec Table",
                        )],
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        tbls = d["content"]["sections"][0]["tables"]
        assert len(tbls) == 1
        assert tbls[0]["caption"] == "Spec Table"

    def test_references_serialized(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        references=[ProceduralReference(
                            ref_type="dm_ref",
                            target_dm_code="DMC-TEST",
                        )],
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        refs = d["content"]["sections"][0]["references"]
        assert len(refs) == 1
        assert refs[0]["type"] == "internalDmRef"
        assert refs[0]["value"] == "DMC-TEST"

    def test_reference_type_mapping(self) -> None:
        for domain, canonical in _REF_TYPE_MAP.items():
            assert isinstance(canonical, str)


# ═══════════════════════════════════════════════════════════════════════
#  SEARCH PROJECTION
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeSearchProjection:
    """searchProjection built from content."""

    def test_search_projection_keys(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        sp = d["searchProjection"]
        for key in ("fullText", "sectionTitles", "figureLabels",
                     "tableCaptions"):
            assert key in sp

    def test_section_titles_collected(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        sp = d["searchProjection"]
        assert "Oil Drain Procedure" in sp["sectionTitles"]

    def test_figure_labels_collected(self) -> None:
        m = make_valid_procedural_module(
            content=ProceduralContent(
                sections=[
                    make_procedural_section(
                        figures=[FigureRef(figure_id="f1", caption="Drain")],
                    ),
                ],
            ),
        )
        d = serialize_procedural_module(m)
        assert "Drain" in d["searchProjection"]["figureLabels"]


# ═══════════════════════════════════════════════════════════════════════
#  VALIDATION
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeValidation:
    """ProceduralValidationResults → canonical validation block."""

    def test_default_validation_none(self) -> None:
        m = make_valid_procedural_module()
        d = serialize_procedural_module(m)
        v = d["validation"]
        assert v["schemaValid"] is False
        assert v["businessRuleValid"] is False
        assert v["status"] == "draft"

    def test_validation_with_results(self) -> None:
        m = make_valid_procedural_module()
        m.validation = ProceduralValidationResults(
            schema_valid=True,
            business_rule_valid=True,
            status=ValidationStatus.APPROVED,
        )
        d = serialize_procedural_module(m)
        v = d["validation"]
        assert v["schemaValid"] is True
        assert v["businessRuleValid"] is True
        assert v["status"] == "approved"

    def test_validation_status_mapping(self) -> None:
        """Every domain ValidationStatus value maps to a canonical string."""
        assert _STATUS_MAP["pending"] == "draft"
        assert _STATUS_MAP["schema_failed"] == "quarantined"
        assert _STATUS_MAP["approved"] == "approved"
        assert _STATUS_MAP["rejected"] == "rejected"
        assert _STATUS_MAP["stored"] == "validated"

    def test_validation_errors_are_objects(self) -> None:
        m = make_valid_procedural_module()
        m.validation = ProceduralValidationResults(
            schema_valid=False,
            status=ValidationStatus.SCHEMA_FAILED,
            errors=["Missing field X"],
        )
        d = serialize_procedural_module(m)
        errs = d["validation"]["errors"]
        assert len(errs) == 1
        assert errs[0]["message"] == "Missing field X"
        assert errs[0]["severity"] == "error"
        assert "code" in errs[0]


# ═══════════════════════════════════════════════════════════════════════
#  LINEAGE
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeLineage:
    """ProceduralLineage → canonical lineage block."""

    def test_lineage_has_canonical_keys(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        lin = d["lineage"]
        for key in ("mappedBy", "mappedAt", "mappingRulesetVersion",
                     "sourceSections"):
            assert key in lin

    def test_lineage_method_mapped(self) -> None:
        """Domain 'rules' → canonical 'rules-only'."""
        d = serialize_procedural_module(make_valid_procedural_module())
        assert d["lineage"]["mappingMethod"] == "rules-only"

    def test_lineage_method_llm_mapped(self) -> None:
        m = make_valid_procedural_module(
            lineage=make_procedural_lineage(mapping_method="llm"),
        )
        d = serialize_procedural_module(m)
        assert d["lineage"]["mappingMethod"] == "hybrid-llm-rules"

    def test_lineage_method_map_completeness(self) -> None:
        expected = {"rules", "llm", "llm+rules", "manual"}
        assert set(_LINEAGE_METHOD_MAP.keys()) == expected

    def test_source_sections_are_objects(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        ss = d["lineage"]["sourceSections"]
        assert len(ss) >= 1
        assert "sectionId" in ss[0]

    def test_confidence_is_object_with_four_fields(self) -> None:
        d = serialize_procedural_module(make_valid_procedural_module())
        conf = d["lineage"]["confidence"]
        for key in ("documentClassification", "dmCodeInference",
                     "sectionTyping", "stepSegmentation"):
            assert key in conf

    def test_confidence_values_from_domain_float(self) -> None:
        m = make_valid_procedural_module(
            lineage=make_procedural_lineage(confidence=0.85),
        )
        d = serialize_procedural_module(m)
        conf = d["lineage"]["confidence"]
        assert conf["documentClassification"] == 0.85
        assert conf["stepSegmentation"] == 0.85

    def test_none_lineage_defaults(self) -> None:
        m = make_valid_procedural_module(lineage=None)
        d = serialize_procedural_module(m)
        lin = d["lineage"]
        assert lin["mappedBy"] == "xstandard-procedural-mapper"
        assert lin["sourceSections"] == []
