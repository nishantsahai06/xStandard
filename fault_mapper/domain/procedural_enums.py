"""Procedural-specific domain enumerations.

Shared enums (MappingStrategy, ValidationStatus, ReviewStatus,
ValidationOutcome, ValidationSeverity, ClassificationMethod,
NoteLikeKind, ItemLocationCode) live in ``fault_mapper.domain.enums``
and are imported directly by any module that needs them.

This file defines ONLY the enums that have no fault-pipeline equivalent.
"""

from __future__ import annotations

from enum import Enum, unique


@unique
class ProceduralSectionType(str, Enum):
    """Classifies a procedural section's role inside the data module.

    Drives ``content.mainProcedure.sections[].sectionType`` in the
    canonical schema.
    """

    SETUP = "setup"
    PROCEDURE = "procedure"
    INSPECTION = "inspection"
    TEST = "test"
    REMOVAL = "removal"
    INSTALLATION = "installation"
    SERVICING = "servicing"
    CLEANING = "cleaning"
    ADJUSTMENT = "adjustment"
    GENERAL = "general"


@unique
class ActionType(str, Enum):
    """Verb classification for the primary action within a step.

    Used for downstream rendering, tooling lookup, and task-time
    estimation.
    """

    REMOVE = "remove"
    INSTALL = "install"
    INSPECT = "inspect"
    TEST = "test"
    ADJUST = "adjust"
    SERVICE = "service"
    CLEAN = "clean"
    LUBRICATE = "lubricate"
    REPLACE = "replace"
    TORQUE = "torque"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    GENERAL = "general"


@unique
class SecurityClassification(str, Enum):
    """S1000D security classification level.

    WHY THIS IS A DOMAIN CONCEPT:
      1. Security classification is a mandatory S1000D data-module
         identity attribute — every DM must carry one.
      2. It drives access control, distribution, and handling
         requirements in any S1000D-compliant CSDB.
      3. The review gate and business rules need to evaluate it
         as a first-class domain constraint, not as a serializer
         string default.

    The values match the S1000D Issue 5.0 security classification
    enumeration.
    """

    UNCLASSIFIED = "01-unclassified"
    RESTRICTED = "02-restricted"
    CONFIDENTIAL = "03-confidential"
    SECRET = "04-secret"
    TOP_SECRET = "05-top-secret"


@unique
class ProceduralModuleType(str, Enum):
    """Discriminator for the procedural module flavour.

    Analogous to ``FaultMode`` in the fault pipeline — drives
    ``moduleType`` in the canonical schema and influences which
    content blocks are populated and which info-code is assigned.
    """

    PROCEDURAL = "procedural"
    DESCRIPTIVE = "descriptive"
