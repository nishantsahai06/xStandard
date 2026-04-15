"""Schema-driven structural validator — validates against ``fault_data_module.schema.json``.

Loads the canonical JSON Schema at import time, serialises the domain
model to a dict, and runs ``jsonschema.validate()`` against it.  Every
``jsonschema.ValidationError`` is converted to a ``ValidationIssue``
with code ``SCHEMA-xxx``.

This **replaces** the hand-coded structural validator as the authoritative
structural check.  The schema is the single source of truth for:
  • required fields & nesting
  • regex patterns on DM code segments
  • enum allowed-value sets (mode, entryType, itemLocationCode, …)
  • conditional requirements (allOf / if-then)
  • additionalProperties enforcement

Anything the schema cannot express (trace quality, LLM confidence,
domain policy) stays in the business-rule validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from fault_mapper.domain.enums import ValidationSeverity
from fault_mapper.domain.models import S1000DFaultDataModule
from fault_mapper.domain.value_objects import ValidationIssue

from fault_mapper.adapters.secondary.module_serializer import serialize_module


# ═══════════════════════════════════════════════════════════════════════
#  SCHEMA LOADING (once at import time)
# ═══════════════════════════════════════════════════════════════════════

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "schemas"
    / "fault_data_module.schema.json"
)

_SCHEMA: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

# Pre-compile the validator for performance
_VALIDATOR = Draft202012Validator(_SCHEMA)


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API — matches StructuralValidatorFn signature
# ═══════════════════════════════════════════════════════════════════════


def validate_against_schema(
    module: S1000DFaultDataModule,
) -> list[ValidationIssue]:
    """Validate the module against the canonical JSON Schema.

    Parameters
    ----------
    module : S1000DFaultDataModule
        The assembled module to validate.

    Returns
    -------
    list[ValidationIssue]
        Zero or more ``SCHEMA-*`` issues.  Empty means structurally valid.
    """
    try:
        instance = serialize_module(module)
    except Exception as exc:
        return [
            ValidationIssue(
                code="SCHEMA-000",
                severity=ValidationSeverity.ERROR,
                message=f"Serialisation failed before schema validation: {exc}",
                field_path=None,
                context=type(exc).__name__,
            )
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
    """Convert a single ``jsonschema.ValidationError`` to a ``ValidationIssue``."""
    # Build a JSON-path-like field path from the error's path deque
    path_parts = [str(p) for p in error.absolute_path]
    field_path = ".".join(path_parts) if path_parts else "(root)"

    # Build the human-readable message
    message = _build_message(error)

    # Extract the failing value for context (truncate if large)
    context = _truncate(repr(error.instance), max_len=120)

    return ValidationIssue(
        code=code,
        severity=ValidationSeverity.ERROR,
        message=message,
        field_path=field_path,
        context=context,
    )


def _build_message(error: jsonschema.ValidationError) -> str:
    """Produce a concise human-readable message from the validation error."""
    validator = error.validator

    if validator == "required":
        missing = error.message  # e.g. "'header' is a required property"
        return f"Missing required property: {missing}"

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

    if validator == "minItems":
        min_items = error.schema.get("minItems", 0)
        return (
            f"Array has fewer than {min_items} item(s) at {_path_str(error)}"
        )

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

    if validator == "const":
        expected = error.schema.get("const", "?")
        return (
            f"Expected constant '{expected}' but got "
            f"'{error.instance}' at {_path_str(error)}"
        )

    if validator == "additionalProperties":
        return f"Additional properties not allowed: {error.message}"

    if validator == "anyOf":
        return f"Value does not match any allowed schema at {_path_str(error)}"

    # Fallback for any other validator keyword
    return f"{error.message} (at {_path_str(error)})"


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _path_str(error: jsonschema.ValidationError) -> str:
    """Return a dotted path string from the error's absolute path."""
    parts = [str(p) for p in error.absolute_path]
    return ".".join(parts) if parts else "(root)"


def _truncate(s: str, max_len: int = 120) -> str:
    """Truncate string with ellipsis if longer than *max_len*."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."
