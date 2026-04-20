"""Schema-driven structural validator for procedural data modules.

Loads ``procedural-data-module.schema.json`` at import time and
validates the serialised dict against it.  Every
``jsonschema.ValidationError`` is converted to a ``ValidationIssue``
with code ``SCHEMA-xxx``.

Validates the **serialized output** (not raw domain objects).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from fault_mapper.domain.enums import ValidationSeverity
from fault_mapper.domain.procedural_models import S1000DProceduralDataModule
from fault_mapper.domain.value_objects import ValidationIssue

from fault_mapper.adapters.secondary.procedural_module_serializer import (
    serialize_procedural_module,
)


# ═══════════════════════════════════════════════════════════════════════
#  SCHEMA LOADING (once at import time)
# ═══════════════════════════════════════════════════════════════════════

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "schemas"
    / "procedural-data-module.schema.json"
)

_SCHEMA: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

_VALIDATOR = Draft202012Validator(_SCHEMA)


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════


def validate_procedural_schema(
    module: S1000DProceduralDataModule,
) -> list[ValidationIssue]:
    """Validate the procedural module against the canonical JSON Schema.

    Returns
    -------
    list[ValidationIssue]
        Zero or more ``SCHEMA-*`` issues.  Empty means structurally valid.
    """
    try:
        instance = serialize_procedural_module(module)
    except Exception as exc:
        return [
            ValidationIssue(
                code="SCHEMA-000",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Serialisation failed before schema validation: {exc}"
                ),
                field_path=None,
                context=type(exc).__name__,
            ),
        ]

    issues: list[ValidationIssue] = []
    error_number = 0

    for error in _VALIDATOR.iter_errors(instance):
        error_number += 1
        code = f"SCHEMA-{error_number:03d}"
        issues.append(_error_to_issue(error, code))

    return issues


# ═══════════════════════════════════════════════════════════════════════
#  ERROR CONVERSION
# ═══════════════════════════════════════════════════════════════════════


def _error_to_issue(
    error: jsonschema.ValidationError,
    code: str,
) -> ValidationIssue:
    path_parts = [str(p) for p in error.absolute_path]
    field_path = ".".join(path_parts) if path_parts else "(root)"
    message = _build_message(error)
    context = _truncate(repr(error.instance), max_len=120)

    return ValidationIssue(
        code=code,
        severity=ValidationSeverity.ERROR,
        message=message,
        field_path=field_path,
        context=context,
    )


def _build_message(error: jsonschema.ValidationError) -> str:
    validator = error.validator

    if validator == "required":
        return f"Missing required property: {error.message}"

    if validator == "pattern":
        pattern = error.schema.get("pattern", "?")
        return (
            f"Value '{error.instance}' does not match pattern "
            f"'{pattern}' at {_path_str(error)}"
        )

    if validator == "enum":
        allowed = error.schema.get("enum", [])
        return (
            f"Value '{error.instance}' is not one of the allowed "
            f"values {allowed} at {_path_str(error)}"
        )

    if validator == "type":
        expected = error.schema.get("type", "?")
        actual = type(error.instance).__name__
        return (
            f"Expected type '{expected}' but got '{actual}' "
            f"at {_path_str(error)}"
        )

    if validator == "minLength":
        min_len = error.schema.get("minLength", 0)
        return (
            f"String too short (min {min_len}) at {_path_str(error)}: "
            f"'{_truncate(str(error.instance), 40)}'"
        )

    if validator == "const":
        expected = error.schema.get("const", "?")
        return (
            f"Expected constant '{expected}' but got "
            f"'{error.instance}' at {_path_str(error)}"
        )

    if validator == "additionalProperties":
        return f"Additional properties not allowed: {error.message}"

    if validator == "minimum":
        minimum = error.schema.get("minimum", "?")
        return (
            f"Value {error.instance} is less than minimum {minimum} "
            f"at {_path_str(error)}"
        )

    if validator == "maximum":
        maximum = error.schema.get("maximum", "?")
        return (
            f"Value {error.instance} exceeds maximum {maximum} "
            f"at {_path_str(error)}"
        )

    if validator == "minItems":
        min_items = error.schema.get("minItems", 0)
        return (
            f"Array has too few items (min {min_items}) "
            f"at {_path_str(error)}"
        )

    return f"{error.message} (at {_path_str(error)})"


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _path_str(error: jsonschema.ValidationError) -> str:
    parts = [str(p) for p in error.absolute_path]
    return ".".join(parts) if parts else "(root)"


def _truncate(s: str, max_len: int = 120) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."
