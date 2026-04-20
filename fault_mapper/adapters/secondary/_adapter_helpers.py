"""Shared pure helpers for secondary adapters.

Stateless utilities extracted to eliminate duplication across
``RulesAdapter`` and ``ProceduralRulesAdapter``.
"""

from __future__ import annotations

import re

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
