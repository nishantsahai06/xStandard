"""Serialise ``S1000DProceduralDataModule`` -> canonical CSDB JSON dict.

Anti-corruption outbound adapter.  Translates inner-hexagon domain
models into the canonical procedural JSON schema shape
(``procedural-data-module.schema.json``).

After Chunk 5 domain enrichment the serializer reads structured VOs
directly instead of fabricating objects from primitive strings.

Design rules
-------------
  - Pure function, no I/O, no side-effects.
  - Emits ONLY keys that exist in the canonical schema.
  - No extra / additional properties.
  - Enum members emit their ``.value`` string.
  - ``None``-valued optional fields emit ``null`` where schema allows.

Remaining fallback bridges (documented, tested, tagged FB-XX)
--------------------------------------------------------------
  FB-01  Provenance file_name/file_type/source_path defaults
  FB-02  Provenance source_document_id "doc_unknown"
  FB-03  DmTitle infoName "Procedure"
  FB-04  Section title "Untitled Section"
  FB-05  Section pageNumbers [1]
  FB-06  Section sectionOrder max(value, 1)
  FB-07  Step text " " (single space, schema minLength:1)
  FB-08  Step stepNumber "1"
  FB-09  Generated IDs uuid-based (sec-, step-, etc.)
  FB-10  SecurityClassification None "01-unclassified"
  FB-11  ResponsiblePartnerCompany None UNKNOWN/Unknown
  FB-12  DataOrigin fallback {isExtracted:True, isHumanReviewed:False}
  FB-13  Lineage None default mapper identity
  FB-14  Validation None draft defaults
  FB-15  Confidence 0.0 null in canonical output
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fault_mapper.domain.models import (
    FigureRef,
    NoteLike,
)
from fault_mapper.domain.procedural_enums import (
    ActionType,
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


# ===================================================================
#  TRANSLATION MAPS  (domain enum -> canonical string)
# ===================================================================

_SECTION_TYPE_MAP: dict[ProceduralSectionType, str] = {
    ProceduralSectionType.SETUP: "preliminary",
    ProceduralSectionType.PROCEDURE: "mainProcedure",
    ProceduralSectionType.INSPECTION: "inspection",
    ProceduralSectionType.TEST: "other",
    ProceduralSectionType.REMOVAL: "mainProcedure",
    ProceduralSectionType.INSTALLATION: "mainProcedure",
    ProceduralSectionType.SERVICING: "mainProcedure",
    ProceduralSectionType.CLEANING: "mainProcedure",
    ProceduralSectionType.ADJUSTMENT: "mainProcedure",
    ProceduralSectionType.GENERAL: "other",
}

_ACTION_TYPE_MAP: dict[ActionType, str] = {
    ActionType.REMOVE: "remove",
    ActionType.INSTALL: "install",
    ActionType.INSPECT: "inspect",
    ActionType.TEST: "test",
    ActionType.ADJUST: "adjust",
    ActionType.SERVICE: "other",
    ActionType.CLEAN: "clean",
    ActionType.LUBRICATE: "other",
    ActionType.REPLACE: "remove",
    ActionType.TORQUE: "other",
    ActionType.CONNECT: "connect",
    ActionType.DISCONNECT: "disconnect",
    ActionType.GENERAL: "other",
}

_LINEAGE_METHOD_MAP: dict[str, str] = {
    "rules": "rules-only",
    "llm": "hybrid-llm-rules",
    "llm+rules": "hybrid-llm-rules",
    "manual": "rules-only",
}

_REQ_TYPE_MAP: dict[str, str] = {
    "personnel": "personnel",
    "equipment": "tool",
    "supply": "consumable",
    "spare": "spare",
    "safety": "precondition",
}

_REF_TYPE_MAP: dict[str, str] = {
    "dm_ref": "internalDmRef",
    "figure_ref": "figureRef",
    "table_ref": "tableRef",
    "external": "externalDocRef",
}

_STATUS_MAP: dict[str, str] = {
    "pending": "draft",
    "schema_failed": "quarantined",
    "completeness_failed": "quarantined",
    "business_rule_failed": "quarantined",
    "review_required": "draft",
    "approved": "approved",
    "rejected": "rejected",
    "stored": "validated",
}

# Canonical top-level keys -- exposed for contract tests.
CANONICAL_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
    "schemaVersion", "moduleType", "csdbRecordId", "source",
    "identAndStatusSection", "content", "searchProjection",
    "validation", "lineage",
})

# All documented fallback codes -- exposed for contract tests.
FALLBACK_CODES: frozenset[str] = frozenset({
    f"FB-{i:02d}" for i in range(1, 16)
})


# ===================================================================
#  PUBLIC API
# ===================================================================


def serialize_procedural_module(
    module: S1000DProceduralDataModule,
) -> dict[str, Any]:
    """Convert a ``S1000DProceduralDataModule`` to a canonical-schema dict."""
    return {
        "schemaVersion": module.schema_version,
        "moduleType": module.module_type.value,
        "csdbRecordId": module.record_id,
        "source": _ser_source(module),
        "identAndStatusSection": _ser_ident_and_status(module),
        "content": _ser_content(module.content),
        "searchProjection": _ser_search_projection(module),
        "validation": _ser_validation(module.validation),
        "lineage": _ser_lineage(module),
    }


# ===================================================================
#  SOURCE  (FB-01, FB-02)
# ===================================================================


def _ser_source(module: S1000DProceduralDataModule) -> dict[str, Any]:
    prov = module.source
    if prov is not None:
        doc_id = prov.source_document_id or "doc_unknown"        # FB-02
        file_name = prov.file_name or "unknown.pdf"              # FB-01
        file_type = prov.file_type or "pdf"                      # FB-01
        source_path = prov.source_path or "/unknown"             # FB-01
    else:
        doc_id = "doc_unknown"                                   # FB-02
        file_name = "unknown.pdf"                                # FB-01
        file_type = "pdf"                                        # FB-01
        source_path = "/unknown"                                 # FB-01

    if not doc_id.startswith("doc_"):
        doc_id = f"doc_{doc_id}"

    return {
        "pipelineDocumentId": doc_id,
        "fileName": file_name,
        "fileType": file_type,
        "sourcePath": source_path,
        "metadata": {
            "uploadedBy": None,
            "uploadedAt": None,
            "pipelineVersion": module.mapping_version or "1.0.0",
        },
    }


# ===================================================================
#  IDENT AND STATUS SECTION  (FB-03, FB-10, FB-11, FB-12)
# ===================================================================


def _ser_ident_and_status(
    module: S1000DProceduralDataModule,
) -> dict[str, Any]:
    header = module.ident_and_status_section
    if header is None:
        return {}

    if isinstance(header.security_classification, SecurityClassification):
        sec_class = header.security_classification.value
    else:
        sec_class = "01-unclassified"                            # FB-10

    return {
        "dmCode": _ser_dm_code(header.dm_code),
        "language": _ser_language(header.language),
        "issueInfo": _ser_issue_info(header.issue_info),
        "issueDate": _ser_issue_date(header.issue_date),
        "dmTitle": _ser_dm_title(header.dm_title),
        "securityClassification": sec_class,
        "responsiblePartnerCompany": _ser_responsible_partner(
            header.responsible_partner_company,
        ),
        "origin": _ser_origin(header),
    }


def _ser_dm_code(c: DmCode) -> dict[str, Any]:
    return {
        "modelIdentCode": c.model_ident_code,
        "systemDiffCode": c.system_diff_code,
        "systemCode": c.system_code,
        "subSystemCode": c.sub_system_code,
        "subSubSystemCode": c.sub_sub_system_code,
        "assyCode": c.assy_code,
        "disassyCode": c.disassy_code,
        "disassyCodeVariant": c.disassy_code_variant,
        "infoCode": c.info_code,
        "infoCodeVariant": c.info_code_variant,
        "itemLocationCode": c.item_location_code,
        "learnCode": c.learn_code,
        "learnEventCode": c.learn_event_code,
        "dmCodeString": c.as_string(),
    }


def _ser_language(lang: Language) -> dict[str, Any]:
    return {
        "languageIsoCode": lang.language_iso_code,
        "countryIsoCode": lang.country_iso_code,
    }


def _ser_issue_info(ii: IssueInfo) -> dict[str, Any]:
    return {"issueNumber": ii.issue_number, "inWork": ii.in_work}


def _ser_issue_date(d: IssueDate) -> dict[str, Any]:
    return {"year": d.year, "month": d.month, "day": d.day}


def _ser_dm_title(t: DmTitle) -> dict[str, Any]:
    d: dict[str, Any] = {
        "techName": t.tech_name,
        "infoName": t.info_name or "Procedure",                 # FB-03
    }
    if t.info_name_variant is not None:
        d["infoNameVariant"] = t.info_name_variant
    return d


def _ser_responsible_partner(
    value: ResponsiblePartnerCompany | None,
) -> dict[str, Any]:
    """FB-11: read VO directly; None -> UNKNOWN defaults."""
    if isinstance(value, ResponsiblePartnerCompany):
        return {
            "enterpriseCode": value.enterprise_code,
            "enterpriseName": value.enterprise_name,
        }
    return {"enterpriseCode": "UNKNOWN", "enterpriseName": "Unknown"}  # FB-11


def _ser_origin(header: ProceduralHeader) -> dict[str, Any]:
    """FB-12: read DataOrigin VO directly; fallback to safe defaults."""
    if isinstance(header.origin, DataOrigin):
        return {
            "isExtracted": header.origin.is_extracted,
            "isHumanReviewed": header.origin.is_human_reviewed,
        }
    return {"isExtracted": True, "isHumanReviewed": False}      # FB-12


# ===================================================================
#  CONTENT  (FB-04 .. FB-09)
# ===================================================================


def _ser_content(c: ProceduralContent) -> dict[str, Any]:
    d: dict[str, Any] = {
        "sections": [_ser_section(s) for s in c.sections],
    }
    if c.preliminary_requirements:
        d["preliminaryRequirements"] = [
            _ser_requirement(r) for r in c.preliminary_requirements
        ]
    if c.warnings:
        d["warnings"] = [_ser_notice(n) for n in c.warnings]
    if c.cautions:
        d["cautions"] = [_ser_notice(n) for n in c.cautions]
    if c.notes:
        d["notes"] = [_ser_notice(n) for n in c.notes]
    return d


def _ser_section(s: ProceduralSection) -> dict[str, Any]:
    section_type = _SECTION_TYPE_MAP.get(s.section_type, "other")

    d: dict[str, Any] = {
        "sectionId": s.section_id or _gen_id("sec"),            # FB-09
        "title": s.title or "Untitled Section",                 # FB-04
        "sectionOrder": max(s.section_order, 1),                # FB-06
        "sectionType": section_type,
        "pageNumbers": s.page_numbers if s.page_numbers else [1],  # FB-05
        "steps": [_ser_step(st) for st in s.steps],
    }

    if s.level is not None and s.level > 1:
        d["level"] = s.level
    if s.raw_section_text is not None:
        d["rawSectionText"] = s.raw_section_text
    if s.sub_sections:
        d["subSections"] = [_ser_section(sub) for sub in s.sub_sections]
    if s.figures:
        d["figures"] = [_ser_figure(f) for f in s.figures]
    if s.tables:
        d["tables"] = [_ser_table(t) for t in s.tables]
    if s.references:
        d["references"] = [_ser_reference(r) for r in s.references]

    return d


def _ser_step(s: ProceduralStep) -> dict[str, Any]:
    action = _ACTION_TYPE_MAP.get(s.action_type, "other")

    d: dict[str, Any] = {
        "stepId": s.step_id or _gen_id("step"),                 # FB-09
        "stepNumber": s.step_number or "1",                     # FB-08
        "text": s.text or " ",                                  # FB-07
        "actionType": action,
    }

    if s.source_chunk_ids:
        d["sourceChunkIds"] = list(s.source_chunk_ids)
    if s.warnings:
        d["warnings"] = [_ser_notice(n) for n in s.warnings]
    if s.cautions:
        d["cautions"] = [_ser_notice(n) for n in s.cautions]
    if s.notes:
        d["notes"] = [_ser_notice(n) for n in s.notes]
    if s.expected_result is not None:
        d["expectedResult"] = s.expected_result
    if s.references:
        d["references"] = [_ser_reference(r) for r in s.references]

    return d


def _ser_requirement(r: ProceduralRequirementItem) -> dict[str, Any]:
    req_type = _REQ_TYPE_MAP.get(r.requirement_type, "other")
    text = r.name or r.safety_text or r.requirement_type
    return {
        "id": r.ident_number or _gen_id("req"),                 # FB-09
        "type": req_type,
        "text": text or "Requirement",
        "quantity": r.quantity if r.quantity else None,
        "unit": r.unit,
    }


def _ser_notice(n: NoteLike) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": n.source_chunk_id or _gen_id("notice"),           # FB-09
        "text": n.text,
    }
    if n.source_chunk_id:
        d["sourceChunkIds"] = [n.source_chunk_id]
    return d


def _ser_figure(f: FigureRef) -> dict[str, Any]:
    return {
        "figureId": f.figure_id or _gen_id("fig"),              # FB-09
        "pageNumber": 1,
        "caption": f.caption,
    }


def _ser_table(t: ProceduralTableRef) -> dict[str, Any]:
    return {
        "tableId": t.table_id or _gen_id("tbl"),                # FB-09
        "pageNumber": 1,
        "caption": t.caption,
    }


def _ser_reference(r: ProceduralReference) -> dict[str, Any]:
    ref_type = _REF_TYPE_MAP.get(r.ref_type, "other")
    value = r.target_dm_code or r.target_id or r.label or "unknown"
    return {"type": ref_type, "value": value}


# ===================================================================
#  SEARCH PROJECTION
# ===================================================================


def _ser_search_projection(
    module: S1000DProceduralDataModule,
) -> dict[str, Any]:
    sections = module.content.sections
    section_titles = [s.title for s in sections if s.title]
    figure_labels: list[str] = []
    table_captions: list[str] = []

    for sec in sections:
        for fig in sec.figures:
            if fig.caption:
                figure_labels.append(fig.caption)
        for tbl in sec.tables:
            if tbl.caption:
                table_captions.append(tbl.caption)

    text_parts: list[str] = []
    for sec in sections:
        if sec.title:
            text_parts.append(sec.title)
        _collect_step_text(sec.steps, text_parts)

    return {
        "fullText": " ".join(text_parts) if text_parts else "",
        "sectionTitles": section_titles,
        "figureLabels": figure_labels,
        "tableCaptions": table_captions,
    }


def _collect_step_text(
    steps: list[ProceduralStep],
    parts: list[str],
) -> None:
    for step in steps:
        if step.text and step.text.strip():
            parts.append(step.text.strip())
        _collect_step_text(step.sub_steps, parts)


# ===================================================================
#  VALIDATION  (FB-14)
# ===================================================================


def _ser_validation(
    v: ProceduralValidationResults | None,
) -> dict[str, Any]:
    if v is None:                                                # FB-14
        return {
            "schemaValid": False,
            "businessRuleValid": False,
            "status": "draft",
            "errors": [],
            "warnings": [],
        }

    canonical_status = _STATUS_MAP.get(v.status.value, "draft")

    errors = [
        {"code": "ERR", "message": e, "severity": "error", "path": None}
        for e in (v.errors or [])
    ]
    warnings = [
        {"code": "WARN", "message": w, "severity": "warning", "path": None}
        for w in (v.warnings or [])
    ]

    return {
        "schemaValid": bool(v.schema_valid),
        "businessRuleValid": bool(v.business_rule_valid),
        "status": canonical_status,
        "errors": errors,
        "warnings": warnings,
    }


# ===================================================================
#  LINEAGE  (FB-13, FB-15)
# ===================================================================


def _ser_lineage(module: S1000DProceduralDataModule) -> dict[str, Any]:
    lin = module.lineage
    now_iso = datetime.now(timezone.utc).isoformat()

    if lin is None:                                              # FB-13
        return {
            "mappedBy": "xstandard-procedural-mapper",
            "mappedAt": now_iso,
            "mappingRulesetVersion": module.mapping_version or "1.0.0",
            "sourceSections": [],
        }

    method = _LINEAGE_METHOD_MAP.get(lin.mapping_method, "rules-only")

    source_sections = [
        {"sectionId": ref.section_id}
        if isinstance(ref, SourceSectionRef)
        else {"sectionId": str(ref)}
        for ref in (lin.source_sections or [])
    ]

    conf = lin.confidence
    if isinstance(conf, ProceduralConfidence):
        conf_block: dict[str, Any] = {
            "documentClassification": conf.document_classification or None,  # FB-15
            "dmCodeInference": conf.dm_code_inference or None,               # FB-15
            "sectionTyping": conf.section_typing or None,                    # FB-15
            "stepSegmentation": conf.step_segmentation or None,              # FB-15
        }
    else:
        conf_value = conf if conf else None                      # FB-15
        conf_block = {
            "documentClassification": conf_value,
            "dmCodeInference": conf_value,
            "sectionTyping": conf_value,
            "stepSegmentation": conf_value,
        }

    d: dict[str, Any] = {
        "mappedBy": lin.mapped_by or "xstandard-procedural-mapper",
        "mappedAt": lin.mapped_at or now_iso,
        "mappingRulesetVersion": lin.mapping_ruleset_version or "1.0.0",
        "sourceSections": source_sections,
    }

    if method:
        d["mappingMethod"] = method

    d["confidence"] = conf_block

    return d


# ===================================================================
#  HELPERS
# ===================================================================


def _gen_id(prefix: str) -> str:
    """Generate a fallback ID (FB-09)."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
