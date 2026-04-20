"""Business-rule validator for procedural data modules.

Validates ``S1000DProceduralDataModule`` against deterministic domain
rules aligned to the canonical schema vocabulary.

Business-rule checks (BIZ-P-* codes)
─────────────────────────────────────
BIZ-P-001  DM title techName must not be empty or whitespace
BIZ-P-002  DM title infoName should be present
BIZ-P-003  Model ident code should not be the placeholder "UNKNOWN"
BIZ-P-004  Sections must be ordered contiguously (no gaps or dups)
BIZ-P-005  Each section must have at least one step or sub-section
BIZ-P-006  Step text must not be empty or whitespace-only
BIZ-P-007  Step numbering should be coherent within a section
BIZ-P-008  Lineage must have non-empty mappedBy and mappedAt
BIZ-P-009  Lineage mappingMethod must be a canonical value
BIZ-P-010  Requirements must have a canonical type
BIZ-P-011  References must have a valid canonical type
BIZ-P-012  Trace warns when LLM-derived fields have low confidence
BIZ-P-013  Classification confidence should meet minimum threshold
BIZ-P-014  Section type must map to a canonical value
BIZ-P-015  Security classification should be a canonical value
"""

from __future__ import annotations

from fault_mapper.domain.enums import (
    MappingStrategy,
    ValidationSeverity,
)
from fault_mapper.domain.procedural_enums import (
    ProceduralSectionType,
    SecurityClassification,
)
from fault_mapper.domain.procedural_models import (
    ProceduralSection,
    ProceduralStep,
    S1000DProceduralDataModule,
)
from fault_mapper.domain.value_objects import ValidationIssue


# ─── Constants (canonical vocabulary) ────────────────────────────────

_CANONICAL_SECTION_TYPES = frozenset({
    "preliminary", "mainProcedure", "postProcedure", "closeUp",
    "inspection", "faultIsolation", "description", "other",
})

_CANONICAL_LINEAGE_METHODS = frozenset({
    "rules-only", "hybrid-ml-rules", "hybrid-llm-rules",
})

_CANONICAL_REQ_TYPES = frozenset({
    "tool", "consumable", "spare", "personnel",
    "reference", "precondition", "other",
})

_CANONICAL_REF_TYPES = frozenset({
    "internalDmRef", "externalDocRef", "figureRef", "tableRef", "other",
})

_CANONICAL_SECURITY_CLASSIFICATIONS = frozenset({
    "01-unclassified", "02-restricted", "03-confidential",
    "04-secret", "05-top-secret",
})

_CANONICAL_VALIDATION_STATUSES = frozenset({
    "draft", "validated", "quarantined", "rejected", "approved",
})

# Section type mapping from domain → canonical (for checking)
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

_MIN_CLASSIFICATION_CONFIDENCE = 0.3
_MIN_LLM_FIELD_CONFIDENCE = 0.5


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════


def validate_procedural_business_rules(
    module: S1000DProceduralDataModule,
) -> list[ValidationIssue]:
    """Run all business-rule checks on a procedural module.

    Returns
    -------
    list[ValidationIssue]
        Zero or more ``BIZ-P-*`` issues.  Empty means business-valid.
    """
    issues: list[ValidationIssue] = []

    _check_header_rules(module, issues)
    _check_section_rules(module, issues)
    _check_lineage_rules(module, issues)
    _check_requirement_rules(module, issues)
    _check_reference_rules(module, issues)
    _check_trace_quality(module, issues)
    _check_classification(module, issues)

    return issues


# ═══════════════════════════════════════════════════════════════════════
#  PRIVATE CHECK FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════


def _check_header_rules(
    module: S1000DProceduralDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-P-001 through BIZ-P-003, BIZ-P-015."""
    header = module.ident_and_status_section
    if header is None:
        return  # schema validator catches this

    title = header.dm_title
    dm = header.dm_code

    # BIZ-P-001: techName must not be empty
    if not title.tech_name or not title.tech_name.strip():
        issues.append(ValidationIssue(
            code="BIZ-P-001",
            severity=ValidationSeverity.ERROR,
            message="DM title techName must not be empty or whitespace.",
            field_path="identAndStatusSection.dmTitle.techName",
            context=repr(title.tech_name),
        ))

    # BIZ-P-002: infoName should be present
    if not title.info_name:
        issues.append(ValidationIssue(
            code="BIZ-P-002",
            severity=ValidationSeverity.WARNING,
            message="DM title infoName is not set — recommended.",
            field_path="identAndStatusSection.dmTitle.infoName",
        ))

    # BIZ-P-003: placeholder model ident code
    if dm.model_ident_code == "UNKNOWN":
        issues.append(ValidationIssue(
            code="BIZ-P-003",
            severity=ValidationSeverity.WARNING,
            message=(
                "Model ident code is the placeholder 'UNKNOWN'. "
                "Source metadata likely lacked a model identifier."
            ),
            field_path="identAndStatusSection.dmCode.modelIdentCode",
            context="UNKNOWN",
        ))

    # BIZ-P-015: security classification canonical value
    sec_class = header.security_classification
    if isinstance(sec_class, SecurityClassification):
        # Domain enum — always valid by construction
        pass
    elif sec_class and sec_class not in _CANONICAL_SECURITY_CLASSIFICATIONS:
        issues.append(ValidationIssue(
            code="BIZ-P-015",
            severity=ValidationSeverity.WARNING,
            message=(
                f"Security classification '{sec_class}' is not a "
                f"canonical value. Expected one of: "
                f"{sorted(_CANONICAL_SECURITY_CLASSIFICATIONS)}"
            ),
            field_path="identAndStatusSection.securityClassification",
            context=str(sec_class),
        ))


def _check_section_rules(
    module: S1000DProceduralDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-P-004 through BIZ-P-007, BIZ-P-014."""
    sections = module.content.sections
    if not sections:
        return

    # BIZ-P-004: contiguous ordering
    orders = [s.section_order for s in sections]
    if orders != sorted(orders):
        issues.append(ValidationIssue(
            code="BIZ-P-004",
            severity=ValidationSeverity.WARNING,
            message="Section ordering is not monotonically increasing.",
            field_path="content.sections[].sectionOrder",
            context=str(orders),
        ))
    if len(set(orders)) != len(orders):
        issues.append(ValidationIssue(
            code="BIZ-P-004",
            severity=ValidationSeverity.ERROR,
            message="Duplicate section_order values detected.",
            field_path="content.sections[].sectionOrder",
            context=str(orders),
        ))

    for i, section in enumerate(sections):
        prefix = f"content.sections[{i}]"

        # BIZ-P-005: at least one step or sub-section
        if not section.steps and not section.sub_sections:
            issues.append(ValidationIssue(
                code="BIZ-P-005",
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Section [{i}] '{section.title}' has no steps "
                    f"and no sub-sections."
                ),
                field_path=f"{prefix}.steps",
                context=section.section_type.value,
            ))

        # BIZ-P-014: section type should map to canonical
        canonical_type = _SECTION_TYPE_MAP.get(section.section_type)
        if canonical_type is None:
            issues.append(ValidationIssue(
                code="BIZ-P-014",
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Section [{i}] has unmapped section type "
                    f"'{section.section_type.value}'."
                ),
                field_path=f"{prefix}.sectionType",
                context=section.section_type.value,
            ))

        # BIZ-P-006 / BIZ-P-007: step validation
        _check_steps(section.steps, prefix, issues)


def _check_steps(
    steps: list[ProceduralStep],
    prefix: str,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-P-006, BIZ-P-007 for steps within a section."""
    seen_numbers: list[str] = []

    for j, step in enumerate(steps):
        step_path = f"{prefix}.steps[{j}]"

        # BIZ-P-006: step text must not be empty
        if not step.text or not step.text.strip():
            issues.append(ValidationIssue(
                code="BIZ-P-006",
                severity=ValidationSeverity.ERROR,
                message=f"Step [{j}] has empty or whitespace-only text.",
                field_path=f"{step_path}.text",
                context=repr(step.text),
            ))

        seen_numbers.append(step.step_number)

        # Recurse into sub-steps
        if step.sub_steps:
            _check_steps(step.sub_steps, step_path, issues)

    # BIZ-P-007: coherent step numbering (no duplicates)
    if len(seen_numbers) != len(set(seen_numbers)):
        issues.append(ValidationIssue(
            code="BIZ-P-007",
            severity=ValidationSeverity.WARNING,
            message="Duplicate step numbers detected in same scope.",
            field_path=f"{prefix}.steps",
            context=str(seen_numbers),
        ))


def _check_lineage_rules(
    module: S1000DProceduralDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-P-008, BIZ-P-009."""
    lineage = module.lineage
    if lineage is None:
        issues.append(ValidationIssue(
            code="BIZ-P-008",
            severity=ValidationSeverity.WARNING,
            message="Lineage block is missing entirely.",
            field_path="lineage",
        ))
        return

    # BIZ-P-008: required lineage fields
    if not lineage.mapped_by or not lineage.mapped_by.strip():
        issues.append(ValidationIssue(
            code="BIZ-P-008",
            severity=ValidationSeverity.ERROR,
            message="Lineage mappedBy must not be empty.",
            field_path="lineage.mappedBy",
        ))

    if not lineage.mapped_at or not lineage.mapped_at.strip():
        issues.append(ValidationIssue(
            code="BIZ-P-008",
            severity=ValidationSeverity.ERROR,
            message="Lineage mappedAt must not be empty.",
            field_path="lineage.mappedAt",
        ))

    # BIZ-P-009: known canonical mapping method
    if lineage.mapping_method:
        # Domain values: rules/llm/llm+rules/manual
        # We check the domain value maps to a canonical value
        from fault_mapper.adapters.secondary.procedural_module_serializer import (
            _LINEAGE_METHOD_MAP,
        )
        mapped = _LINEAGE_METHOD_MAP.get(lineage.mapping_method)
        if mapped is None and lineage.mapping_method not in _CANONICAL_LINEAGE_METHODS:
            issues.append(ValidationIssue(
                code="BIZ-P-009",
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Lineage mappingMethod '{lineage.mapping_method}' "
                    f"does not map to a canonical value. "
                    f"Canonical: {sorted(_CANONICAL_LINEAGE_METHODS)}"
                ),
                field_path="lineage.mappingMethod",
                context=lineage.mapping_method,
            ))


def _check_requirement_rules(
    module: S1000DProceduralDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-P-010."""
    from fault_mapper.adapters.secondary.procedural_module_serializer import (
        _REQ_TYPE_MAP,
    )
    for i, req in enumerate(module.content.preliminary_requirements):
        mapped = _REQ_TYPE_MAP.get(req.requirement_type)
        if mapped is None and req.requirement_type not in _CANONICAL_REQ_TYPES:
            issues.append(ValidationIssue(
                code="BIZ-P-010",
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Requirement [{i}] has type '{req.requirement_type}' "
                    f"which does not map to a canonical value."
                ),
                field_path=(
                    f"content.preliminaryRequirements[{i}].type"
                ),
                context=req.requirement_type,
            ))


def _check_reference_rules(
    module: S1000DProceduralDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-P-011."""
    from fault_mapper.adapters.secondary.procedural_module_serializer import (
        _REF_TYPE_MAP,
    )
    for i, section in enumerate(module.content.sections):
        for j, ref in enumerate(section.references):
            if not ref.ref_type or not ref.ref_type.strip():
                issues.append(ValidationIssue(
                    code="BIZ-P-011",
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Reference [{j}] in section [{i}] has empty type."
                    ),
                    field_path=(
                        f"content.sections[{i}].references[{j}].type"
                    ),
                ))
            elif (
                ref.ref_type not in _REF_TYPE_MAP
                and ref.ref_type not in _CANONICAL_REF_TYPES
            ):
                issues.append(ValidationIssue(
                    code="BIZ-P-011",
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Reference [{j}] in section [{i}] has type "
                        f"'{ref.ref_type}' not in canonical vocabulary."
                    ),
                    field_path=(
                        f"content.sections[{i}].references[{j}].type"
                    ),
                    context=ref.ref_type,
                ))


def _check_trace_quality(
    module: S1000DProceduralDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-P-012."""
    trace = module.trace
    if trace is None or not trace.field_origins:
        return

    low_conf_fields: list[str] = []
    for field_name, origin in trace.field_origins.items():
        if (
            origin.strategy is MappingStrategy.LLM
            and origin.confidence < _MIN_LLM_FIELD_CONFIDENCE
        ):
            low_conf_fields.append(
                f"{field_name} ({origin.confidence:.2f})"
            )

    if low_conf_fields:
        issues.append(ValidationIssue(
            code="BIZ-P-012",
            severity=ValidationSeverity.WARNING,
            message=(
                f"{len(low_conf_fields)} LLM-derived field(s) have "
                f"confidence below {_MIN_LLM_FIELD_CONFIDENCE}."
            ),
            field_path="trace.field_origins",
            context=", ".join(low_conf_fields[:5]),
        ))


def _check_classification(
    module: S1000DProceduralDataModule,
    issues: list[ValidationIssue],
) -> None:
    """BIZ-P-013."""
    cls = module.classification
    if cls is None:
        return

    if cls.confidence < _MIN_CLASSIFICATION_CONFIDENCE:
        issues.append(ValidationIssue(
            code="BIZ-P-013",
            severity=ValidationSeverity.WARNING,
            message=(
                f"Classification confidence ({cls.confidence:.3f}) is "
                f"below minimum threshold "
                f"({_MIN_CLASSIFICATION_CONFIDENCE})."
            ),
            field_path="classification.confidence",
            context=f"{cls.confidence:.3f}",
        ))
