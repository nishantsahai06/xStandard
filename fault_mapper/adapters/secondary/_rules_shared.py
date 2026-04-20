"""Shared pure helpers for rules-engine adapters.

Both ``rules_adapter.py`` (fault) and ``procedural_rules_adapter.py``
(procedural) depend on an identical set of small utilities.  This
module hosts them once so there is a single source of truth.

Everything here is deterministic, side-effect-free (except
``make_record_id`` which uses UUID v4 by design and
``today_issue_date`` which reads the clock), and free of any
fault- or procedural-specific knowledge.

Design note
───────────
A free-function module is preferred over a shared base class.  Rules
adapters intentionally have divergent APIs (``FaultMode`` vs
``ProceduralModuleType``) and a common supertype would force brittle
TYPE_CHECKING gymnastics and leak concepts across the two pipelines.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fault_mapper.domain.value_objects import IssueDate, IssueInfo, Language

__all__ = [
    "WS_RE",
    "collapse_whitespace",
    "safe_get",
    "make_record_id",
    "today_issue_date",
    "issue_info_from",
    "language_from",
]


WS_RE = re.compile(r"\s+")


def collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single space and strip."""
    return WS_RE.sub(" ", text).strip()


def safe_get(meta: dict, *keys: str, default: str = "") -> str:
    """Walk nested dicts safely, returning *default* on any miss."""
    current: object = meta
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return str(current) if current is not None else default


def make_record_id() -> str:
    """Generate a unique record identifier (UUID v4)."""
    return str(uuid.uuid4())


def today_issue_date() -> IssueDate:
    """Return today's UTC date formatted per S1000D convention."""
    today = datetime.now(timezone.utc).date()
    return IssueDate(
        year=f"{today.year:04d}",
        month=f"{today.month:02d}",
        day=f"{today.day:02d}",
    )


def issue_info_from(issue_number: str, in_work: str) -> IssueInfo:
    """Build an ``IssueInfo`` from raw config primitives."""
    return IssueInfo(issue_number=issue_number, in_work=in_work)


def language_from(language_iso: str, country_iso: str) -> Language:
    """Build a ``Language`` from raw config primitives."""
    return Language(
        language_iso_code=language_iso,
        country_iso_code=country_iso,
    )
