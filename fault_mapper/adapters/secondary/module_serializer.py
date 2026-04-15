"""Serialise ``S1000DFaultDataModule`` to a plain dict that matches
the canonical ``fault_data_module.schema.json`` shape (camelCase keys,
schema-expected value types).

This is a **secondary adapter** — its only job is bridging the domain
model's Python-native attribute names to the JSON schema's camelCase
contract so that ``jsonschema.validate()`` can be applied.

Design rules
────────────
• Pure function, no I/O, no side-effects.
• ``None``-valued optional fields are **omitted** from the dict so that
  ``additionalProperties: false`` in the schema is not violated by
  spurious ``null`` keys the schema never declared.
• Enum members emit their ``.value`` string automatically because every
  domain enum is ``str``-backed.
"""

from __future__ import annotations

from typing import Any

from fault_mapper.domain.enums import FaultMode
from fault_mapper.domain.models import (
    ApplicRef,
    Classification,
    CloseRequirements,
    CommonInfo,
    DetectedLruItem,
    DetectedSruItem,
    DetectionInfo,
    DetailedFaultDescription,
    FaultContent,
    FaultDescription,
    FaultEntry,
    FaultHeader,
    FaultIsolationContent,
    FaultReportingContent,
    FigureRef,
    FunctionalItemRef,
    IsolationResult,
    IsolationStep,
    IsolationStepBranch,
    ItemRequirement,
    LocateAndRepair,
    LocateAndRepairLruItem,
    LocateAndRepairSruItem,
    Lru,
    NoteLike,
    PreliminaryRequirements,
    Ref,
    Repair,
    ReqCondGroup,
    ReqSafety,
    RequiredPerson,
    S1000DFaultDataModule,
    Sru,
    TypedText,
    ValidationResults,
    XmlMeta,
)
from fault_mapper.domain.value_objects import (
    DmCode,
    DmTitle,
    IssueDate,
    IssueInfo,
    Language,
)


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════


def serialize_module(module: S1000DFaultDataModule) -> dict[str, Any]:
    """Convert a ``S1000DFaultDataModule`` to a schema-conformant dict.

    The returned dict uses camelCase keys matching every property in
    ``fault_data_module.schema.json`` and can be passed directly to
    ``jsonschema.validate(instance=…)``.
    """
    d: dict[str, Any] = {
        "recordId": module.record_id,
        "recordType": module.record_type,
        "mode": module.mode.value,
        "validationStatus": module.validation_status.value,
    }

    # Flatten provenance → top-level schema fields
    if module.provenance is not None:
        d["sourceDocumentId"] = module.provenance.source_document_id
        d["sourceSectionIds"] = list(module.provenance.source_section_ids)
        if module.provenance.source_pages:
            d["sourcePages"] = list(module.provenance.source_pages)

    # Header
    if module.header is not None:
        d["header"] = _ser_header(module.header)

    # Content
    d["content"] = _ser_content(module.content)

    # Optional top-level fields
    _set_if(d, "mappingVersion", module.mapping_version)
    if module.classification is not None:
        d["classification"] = _ser_classification(module.classification)
    if module.validation_results is not None:
        d["validationResults"] = _ser_validation_results(
            module.validation_results
        )
    if module.xml_meta is not None:
        d["xmlMeta"] = _ser_xml_meta(module.xml_meta)

    return d


# ═══════════════════════════════════════════════════════════════════════
#  HEADER SERIALISATION
# ═══════════════════════════════════════════════════════════════════════


def _ser_header(h: FaultHeader) -> dict[str, Any]:
    return {
        "dmCode": _ser_dm_code(h.dm_code),
        "language": _ser_language(h.language),
        "issueInfo": _ser_issue_info(h.issue_info),
        "issueDate": _ser_issue_date(h.issue_date),
        "dmTitle": _ser_dm_title(h.dm_title),
    }


def _ser_dm_code(c: DmCode) -> dict[str, Any]:
    d: dict[str, Any] = {
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
    }
    _set_if(d, "learnCode", c.learn_code)
    _set_if(d, "learnEventCode", c.learn_event_code)
    return d


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
    d: dict[str, Any] = {"techName": t.tech_name}
    _set_if(d, "infoName", t.info_name)
    _set_if(d, "infoNameVariant", t.info_name_variant)
    return d


# ═══════════════════════════════════════════════════════════════════════
#  CONTENT SERIALISATION
# ═══════════════════════════════════════════════════════════════════════


def _ser_content(c: FaultContent) -> dict[str, Any]:
    d: dict[str, Any] = {
        "refs": [_ser_ref(r) for r in c.refs],
        "warningsAndCautions": [_ser_note_like(n) for n in c.warnings_and_cautions],
    }

    if c.applic_refs:
        d["referencedApplicGroup"] = [
            _ser_applic_ref(a) for a in c.applic_refs
        ]

    if c.preliminary_rqmts is not None:
        d["preliminaryRqmts"] = _ser_prelim_rqmts(c.preliminary_rqmts)

    # Exactly one of these is non-null per the schema allOf constraint
    if c.fault_reporting is not None:
        d["faultReporting"] = _ser_fault_reporting(c.fault_reporting)
        d["faultIsolation"] = None
    elif c.fault_isolation is not None:
        d["faultReporting"] = None
        d["faultIsolation"] = _ser_fault_isolation(c.fault_isolation)
    else:
        d["faultReporting"] = None
        d["faultIsolation"] = None

    return d


# ─── Shared building-block serialisers ───────────────────────────────


def _ser_ref(r: Ref) -> dict[str, Any]:
    d: dict[str, Any] = {"type": r.type}
    _set_if(d, "targetDmCode", r.target_dm_code)
    _set_if(d, "targetId", r.target_id)
    _set_if(d, "label", r.label)
    return d


def _ser_applic_ref(a: ApplicRef) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "applicabilityId", a.applicability_id)
    _set_if(d, "label", a.label)
    return d


def _ser_note_like(n: NoteLike) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": n.kind.value, "text": n.text}
    _set_if(d, "sourceChunkId", n.source_chunk_id)
    return d


def _ser_typed_text(t: TypedText) -> dict[str, Any]:
    d: dict[str, Any] = {"text": t.text}
    _set_if(d, "sourceChunkId", t.source_chunk_id)
    return d


def _ser_figure_ref(f: FigureRef) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "figureId", f.figure_id)
    _set_if(d, "caption", f.caption)
    return d


def _ser_common_info(ci: CommonInfo) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "title", ci.title)
    if ci.paragraphs:
        d["paragraphs"] = [_ser_typed_text(p) for p in ci.paragraphs]
    if ci.figures:
        d["figures"] = [_ser_figure_ref(f) for f in ci.figures]
    return d


# ─── Requirements serialisers ───────────────────────────────────────


def _ser_req_cond_group(g: ReqCondGroup) -> dict[str, Any]:
    return {"conditions": [_ser_typed_text(c) for c in g.conditions]}


def _ser_req_safety(s: ReqSafety) -> dict[str, Any]:
    return {
        "warnings": [_ser_note_like(n) for n in s.warnings],
        "cautions": [_ser_note_like(n) for n in s.cautions],
        "notes": [_ser_note_like(n) for n in s.notes],
    }


def _ser_required_person(p: RequiredPerson) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "role", p.role)
    if p.count != 1:
        d["count"] = p.count
    _set_if(d, "skillLevel", p.skill_level)
    return d


def _ser_item_requirement(ir: ItemRequirement) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "name", ir.name)
    _set_if(d, "identNumber", ir.ident_number)
    if ir.quantity:
        d["quantity"] = ir.quantity
    _set_if(d, "unit", ir.unit)
    _set_if(d, "sourceTableId", ir.source_table_id)
    return d


def _ser_prelim_rqmts(pr: PreliminaryRequirements) -> dict[str, Any]:
    d: dict[str, Any] = {
        "reqCondGroup": _ser_req_cond_group(pr.req_cond_group),
        "reqSupportEquips": [_ser_item_requirement(i) for i in pr.req_support_equips],
        "reqSupplies": [_ser_item_requirement(i) for i in pr.req_supplies],
        "reqSpares": [_ser_item_requirement(i) for i in pr.req_spares],
        "reqSafety": _ser_req_safety(pr.req_safety),
    }
    if pr.production_maint_data:
        d["productionMaintData"] = [
            _ser_typed_text(t) for t in pr.production_maint_data
        ]
    if pr.req_persons:
        d["reqPersons"] = [_ser_required_person(p) for p in pr.req_persons]
    if pr.req_tech_info_group:
        d["reqTechInfoGroup"] = [_ser_ref(r) for r in pr.req_tech_info_group]
    return d


def _ser_close_rqmts(cr: CloseRequirements) -> dict[str, Any]:
    d: dict[str, Any] = {
        "reqCondGroup": _ser_req_cond_group(cr.req_cond_group),
        "reqSupportEquips": [_ser_item_requirement(i) for i in cr.req_support_equips],
        "reqSupplies": [_ser_item_requirement(i) for i in cr.req_supplies],
        "reqSpares": [_ser_item_requirement(i) for i in cr.req_spares],
        "reqSafety": _ser_req_safety(cr.req_safety),
    }
    return d


# ═══════════════════════════════════════════════════════════════════════
#  FAULT REPORTING SERIALISATION
# ═══════════════════════════════════════════════════════════════════════


def _ser_fault_reporting(fr: FaultReportingContent) -> dict[str, Any]:
    d: dict[str, Any] = {
        "faultEntries": [_ser_fault_entry(e) for e in fr.fault_entries],
    }
    if fr.common_info is not None:
        d["commonInfo"] = _ser_common_info(fr.common_info)
    if fr.preliminary_rqmts is not None:
        d["preliminaryRqmts"] = _ser_prelim_rqmts(fr.preliminary_rqmts)
    if fr.close_rqmts is not None:
        d["closeRqmts"] = _ser_close_rqmts(fr.close_rqmts)
    return d


def _ser_fault_entry(e: FaultEntry) -> dict[str, Any]:
    d: dict[str, Any] = {"entryType": e.entry_type.value}
    _set_if(d, "id", e.id)
    _set_if(d, "faultCode", e.fault_code)
    if e.fault_descr is not None:
        d["faultDescr"] = _ser_fault_descr(e.fault_descr)
    if e.detection_info is not None:
        d["detectionInfo"] = _ser_detection_info(e.detection_info)
    if e.locate_and_repair is not None:
        d["locateAndRepair"] = _ser_locate_and_repair(e.locate_and_repair)
    _set_if(d, "remarks", e.remarks)
    return d


def _ser_fault_descr(fd: FaultDescription) -> dict[str, Any]:
    d: dict[str, Any] = {"descr": fd.descr}
    if fd.detailed is not None:
        d["detailedFaultDescr"] = _ser_detailed_fault_descr(fd.detailed)
    return d


def _ser_detailed_fault_descr(dd: DetailedFaultDescription) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "viewLocation", dd.view_location)
    _set_if(d, "systemLocation", dd.system_location)
    _set_if(d, "systemName", dd.system_name)
    _set_if(d, "faultySubSystem", dd.faulty_sub_system)
    _set_if(d, "systemIdent", dd.system_ident)
    _set_if(d, "systemPosition", dd.system_position)
    _set_if(d, "faultEquip", dd.fault_equip)
    _set_if(d, "faultMessageIndication", dd.fault_message_indication)
    _set_if(d, "faultMessageBody", dd.fault_message_body)
    _set_if(d, "faultCond", dd.fault_cond)
    return d


# ─── LRU / SRU / Repair hierarchy ───────────────────────────────────


def _ser_lru(lru: Lru) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "name", lru.name)
    _set_if(d, "shortName", lru.short_name)
    _set_if(d, "identNumber", lru.ident_number)
    if lru.part_ref is not None:
        d["partRef"] = _ser_ref(lru.part_ref)
    if lru.functional_item_ref is not None:
        d["functionalItemRef"] = _ser_functional_item_ref(
            lru.functional_item_ref
        )
    return d


def _ser_sru(sru: Sru) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "name", sru.name)
    _set_if(d, "shortName", sru.short_name)
    _set_if(d, "identNumber", sru.ident_number)
    if sru.part_ref is not None:
        d["partRef"] = _ser_ref(sru.part_ref)
    if sru.functional_item_ref is not None:
        d["functionalItemRef"] = _ser_functional_item_ref(
            sru.functional_item_ref
        )
    return d


def _ser_functional_item_ref(fi: FunctionalItemRef) -> dict[str, Any]:
    d: dict[str, Any] = {
        "functionalItemNumber": fi.functional_item_number,
    }
    _set_if(d, "functionalItemType", fi.functional_item_type)
    return d


def _ser_repair(r: Repair) -> dict[str, Any]:
    return {"refs": [_ser_ref(ref) for ref in r.refs]}


# ─── Detection info ──────────────────────────────────────────────────


def _ser_detection_info(di: DetectionInfo) -> dict[str, Any]:
    d: dict[str, Any] = {
        "detectedLruItem": _ser_detected_lru_item(di.detected_lru_item),
    }
    _set_if(d, "detectionType", di.detection_type)
    return d


def _ser_detected_lru_item(item: DetectedLruItem) -> dict[str, Any]:
    d: dict[str, Any] = {"lrus": [_ser_lru(lru) for lru in item.lrus]}
    if item.fault_probability is not None:
        d["faultProbability"] = item.fault_probability
    _set_if(d, "remarks", item.remarks)
    if item.detected_sru_item is not None:
        d["detectedSruItem"] = _ser_detected_sru_item(item.detected_sru_item)
    return d


def _ser_detected_sru_item(item: DetectedSruItem) -> dict[str, Any]:
    d: dict[str, Any] = {"srus": [_ser_sru(s) for s in item.srus]}
    if item.fault_probability is not None:
        d["faultProbability"] = item.fault_probability
    _set_if(d, "remarks", item.remarks)
    return d


# ─── Locate and repair ──────────────────────────────────────────────


def _ser_locate_and_repair(lar: LocateAndRepair) -> dict[str, Any]:
    return {
        "locateAndRepairLruItem": _ser_lar_lru_item(
            lar.locate_and_repair_lru_item
        ),
    }


def _ser_lar_lru_item(item: LocateAndRepairLruItem) -> dict[str, Any]:
    d: dict[str, Any] = {"lrus": [_ser_lru(lru) for lru in item.lrus]}
    if item.fault_probability is not None:
        d["faultProbability"] = item.fault_probability
    if item.repair is not None:
        d["repair"] = _ser_repair(item.repair)
    _set_if(d, "remarks", item.remarks)
    if item.locate_and_repair_sru_item is not None:
        d["locateAndRepairSruItem"] = _ser_lar_sru_item(
            item.locate_and_repair_sru_item
        )
    return d


def _ser_lar_sru_item(item: LocateAndRepairSruItem) -> dict[str, Any]:
    d: dict[str, Any] = {"srus": [_ser_sru(s) for s in item.srus]}
    if item.fault_probability is not None:
        d["faultProbability"] = item.fault_probability
    if item.repair is not None:
        d["repair"] = _ser_repair(item.repair)
    _set_if(d, "remarks", item.remarks)
    return d


# ═══════════════════════════════════════════════════════════════════════
#  FAULT ISOLATION SERIALISATION
# ═══════════════════════════════════════════════════════════════════════


def _ser_fault_isolation(fi: FaultIsolationContent) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if fi.common_info is not None:
        d["commonInfo"] = _ser_common_info(fi.common_info)
    if fi.preliminary_rqmts is not None:
        d["preliminaryRqmts"] = _ser_prelim_rqmts(fi.preliminary_rqmts)
    if fi.close_rqmts is not None:
        d["closeRqmts"] = _ser_close_rqmts(fi.close_rqmts)
    if fi.fault_isolation_steps:
        d["faultIsolationSteps"] = [
            _ser_isolation_step(s) for s in fi.fault_isolation_steps
        ]
    return d


def _ser_isolation_step(s: IsolationStep) -> dict[str, Any]:
    d: dict[str, Any] = {
        "stepNumber": s.step_number,
        "instruction": s.instruction,
    }
    _set_if(d, "question", s.question)
    if s.yes_group is not None:
        d["yesGroup"] = _ser_branch(s.yes_group)
    if s.no_group is not None:
        d["noGroup"] = _ser_branch(s.no_group)
    _set_if(d, "decision", s.decision)
    _set_if(d, "sourceChunkId", s.source_chunk_id)
    if s.refs:
        d["refs"] = [_ser_ref(r) for r in s.refs]
    return d


def _ser_branch(b: IsolationStepBranch) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if b.next_steps:
        d["nextSteps"] = [_ser_isolation_step(s) for s in b.next_steps]
    if b.result is not None:
        d["result"] = _ser_isolation_result(b.result)
    return d


def _ser_isolation_result(r: IsolationResult) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if r.fault_confirmed:
        d["faultConfirmed"] = r.fault_confirmed
    if r.faulty_item is not None:
        d["faultyItem"] = _ser_lru(r.faulty_item)
    _set_if(d, "repairAction", r.repair_action)
    if r.repair_ref is not None:
        d["repairRef"] = _ser_ref(r.repair_ref)
    return d


# ═══════════════════════════════════════════════════════════════════════
#  METADATA SERIALISATION
# ═══════════════════════════════════════════════════════════════════════


def _ser_classification(c: Classification) -> dict[str, Any]:
    return {
        "domain": c.domain,
        "confidence": c.confidence,
        "method": c.method.value,
    }


def _ser_validation_results(vr: ValidationResults) -> dict[str, Any]:
    d: dict[str, Any] = {
        "schema": vr.schema.value,
        "completeness": vr.completeness.value,
        "xsdAlignment": vr.xsd_alignment.value,
        "businessRules": vr.business_rules.value,
    }
    if vr.semantic_confidence:
        d["semanticConfidence"] = vr.semantic_confidence
    return d


def _ser_xml_meta(xm: XmlMeta) -> dict[str, Any]:
    d: dict[str, Any] = {}
    _set_if(d, "id", xm.id)
    _set_if(d, "schemaSource", xm.schema_source)
    _set_if(d, "serializationTarget", xm.serialization_target)
    return d


# ═══════════════════════════════════════════════════════════════════════
#  UTILITIES
# ═══════════════════════════════════════════════════════════════════════


def _set_if(d: dict[str, Any], key: str, value: Any) -> None:
    """Insert *key* → *value* into *d* only when *value* is not None."""
    if value is not None:
        d[key] = value
