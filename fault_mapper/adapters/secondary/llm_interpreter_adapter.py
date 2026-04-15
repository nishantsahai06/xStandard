"""Concrete LLM interpreter adapter — implements ``LlmInterpreterPort``.

This adapter wraps an OpenAI-compatible chat-completions client and
translates raw LLM JSON responses into the domain value-object types
that the application layer expects.

Critical rules
──────────────
• This adapter NEVER returns target-model instances (FaultEntry, etc.).
• It returns ONLY intermediate interpretation value objects.
• All prompt engineering lives here — the domain/application layer
  must not contain any LLM prompt text.
• All LLM calls are synchronous from the caller's perspective.  If
  the underlying client is async the adapter bridges internally.

LLM client protocol
────────────────────
The adapter expects a *callable* with the following signature (the
"chat completions" shape used by both OpenAI and Anthropic SDKs)::

    def __call__(
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict | None = None,
    ) -> LlmResponse

``LlmResponse`` must expose ``.choices[0].message.content`` (str)
or equivalently be subscriptable as ``response["choices"][0]["message"]["content"]``.

If the deployment uses a different shape the infrastructure factory
can inject a thin wrapper that conforms to this protocol.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from fault_mapper.domain.enums import FaultMode, TableType
from fault_mapper.domain.models import SchematicsItem, Section, TableAsset
from fault_mapper.domain.value_objects import (
    FaultDescriptionInterpretation,
    FaultModeInterpretation,
    FaultRelevanceAssessment,
    IsolationStepInterpretation,
    LruSruExtraction,
    SchematicCorrelation,
    TableClassification,
)
from fault_mapper.infrastructure.config import LlmConfig


logger = logging.getLogger(__name__)


# ─── LLM client protocol ────────────────────────────────────────────


@runtime_checkable
class LlmClient(Protocol):
    """Minimal protocol for an OpenAI-compatible chat-completions client."""

    def __call__(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> Any:
        ...


# ─── Helpers ─────────────────────────────────────────────────────────


def _extract_content(response: Any) -> str:
    """Extract the text content from an OpenAI-compatible response.

    Supports both attribute access (``response.choices[0].message.content``)
    and dict access (``response["choices"][0]["message"]["content"]``).
    """
    try:
        # SDK object style (openai>=1.0)
        return response.choices[0].message.content  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        pass
    try:
        # Dict style (httpx / raw JSON)
        return response["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        pass
    # Last resort: maybe the response IS the string (test doubles)
    if isinstance(response, str):
        return response
    raise ValueError(
        f"Cannot extract content from LLM response of type {type(response).__name__}"
    )


def _parse_json(raw: str) -> Any:
    """Parse JSON from an LLM response, stripping markdown fences if present."""
    text = raw.strip()
    # Strip ```json ... ``` fences
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce to float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce to int safely."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Coerce to bool safely."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return default


def _section_summary(section: Section, max_chars: int = 2000) -> str:
    """Build a compact text summary of a section for inclusion in prompts."""
    parts = [f"Title: {section.section_title or '(untitled)'}"]
    if section.section_type:
        parts.append(f"Type: {section.section_type}")
    text = section.section_text or ""
    if text:
        parts.append(f"Text:\n{text[:max_chars]}")
    if section.tables:
        for t in section.tables[:3]:
            parts.append(f"Table: {t.caption or '(no caption)'}")
            if t.headers:
                parts.append(f"  Headers: {', '.join(t.headers)}")
            if t.markdown_summary:
                parts.append(f"  Summary: {t.markdown_summary[:500]}")
    return "\n".join(parts)


def _table_summary(table: TableAsset, max_rows: int = 10) -> str:
    """Build a compact text summary of a table for inclusion in prompts."""
    parts = [f"Caption: {table.caption or '(no caption)'}"]
    if table.headers:
        parts.append(f"Headers: {', '.join(table.headers)}")
    if table.rows:
        for row in table.rows[:max_rows]:
            parts.append(f"  Row: {row}")
    if table.markdown_summary:
        parts.append(f"Markdown summary: {table.markdown_summary[:800]}")
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════


class LlmInterpreterAdapter:
    """Adapter that fulfils ``LlmInterpreterPort`` using an LLM backend.

    All 7 port methods are implemented.  Each follows the pattern:
    1. Build a system + user prompt with a JSON output schema.
    2. Call the LLM client.
    3. Parse the JSON response into typed domain value objects.
    4. On parse failure → return a conservative / empty result with
       ``confidence=0.0`` and a ``reasoning`` that explains the failure.
    """

    def __init__(
        self,
        llm_client: LlmClient,
        config: LlmConfig,
    ) -> None:
        self._client = llm_client
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    # ── private call helper ──────────────────────────────────────

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Call the LLM and return the raw content string."""
        response = self._client(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )
        return _extract_content(response)

    # ══════════════════════════════════════════════════════════════
    #  1.  assess_fault_relevance
    # ══════════════════════════════════════════════════════════════

    def assess_fault_relevance(
        self,
        section: Section,
    ) -> FaultRelevanceAssessment:
        """Assess whether a section contains fault-relevant content."""
        system_prompt = (
            "You are an aerospace technical document analyst. "
            "Determine whether the following document section contains "
            "fault-relevant content (fault reporting, fault isolation, "
            "troubleshooting, LRU/SRU replacement, etc.).\n\n"
            "Respond with a JSON object:\n"
            '{"is_relevant": true/false, "confidence": 0.0-1.0, '
            '"reasoning": "brief explanation"}'
        )
        user_prompt = _section_summary(section)

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            return FaultRelevanceAssessment(
                is_relevant=_safe_bool(data.get("is_relevant", False)),
                confidence=_safe_float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning("LLM fault relevance assessment failed: %s", exc)
            return FaultRelevanceAssessment(
                is_relevant=False,
                confidence=0.0,
                reasoning=f"LLM call failed: {exc}",
            )

    # ══════════════════════════════════════════════════════════════
    #  2.  interpret_fault_mode
    # ══════════════════════════════════════════════════════════════

    def interpret_fault_mode(
        self,
        sections: list[Section],
    ) -> FaultModeInterpretation:
        """Determine fault-reporting vs fault-isolation via LLM."""
        system_prompt = (
            "You are an S1000D technical document analyst. "
            "Given the following fault-relevant document sections, "
            "determine whether they primarily describe:\n"
            "  - 'faultReporting': fault descriptions, detected/observed "
            "faults, fault codes, LRU/SRU lists\n"
            "  - 'faultIsolation': troubleshooting steps, decision trees, "
            "isolation procedures, yes/no diagnostic flows\n\n"
            "Respond with a JSON object:\n"
            '{"mode": "faultReporting" or "faultIsolation", '
            '"confidence": 0.0-1.0, "reasoning": "brief explanation"}'
        )
        summaries = [_section_summary(s, max_chars=1000) for s in sections[:10]]
        user_prompt = "\n\n---\n\n".join(summaries)

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            mode_str = str(data.get("mode", "faultReporting"))
            try:
                mode = FaultMode(mode_str)
            except ValueError:
                mode = FaultMode.FAULT_REPORTING
            return FaultModeInterpretation(
                mode=mode,
                confidence=_safe_float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning("LLM fault mode interpretation failed: %s", exc)
            return FaultModeInterpretation(
                mode=FaultMode.FAULT_REPORTING,
                confidence=0.0,
                reasoning=f"LLM call failed: {exc}",
            )

    # ══════════════════════════════════════════════════════════════
    #  3.  interpret_fault_descriptions
    # ══════════════════════════════════════════════════════════════

    def interpret_fault_descriptions(
        self,
        text: str,
        context: str,
    ) -> list[FaultDescriptionInterpretation]:
        """Extract structured fault descriptions from unstructured text."""
        system_prompt = (
            "You are an S1000D fault-reporting analyst. "
            "Extract all fault descriptions from the provided text.\n\n"
            "For each fault, extract:\n"
            "  - description (required): a concise fault description\n"
            "  - system_name: the aircraft system name if mentioned\n"
            "  - fault_code_suggestion: any fault code referenced\n"
            "  - fault_equipment: equipment involved\n"
            "  - fault_message: fault indicator message text\n"
            "  - confidence: 0.0–1.0\n\n"
            "Respond with a JSON object:\n"
            '{"faults": [{"description": "...", "system_name": "...", '
            '"fault_code_suggestion": "...", "fault_equipment": "...", '
            '"fault_message": "...", "confidence": 0.9}, ...]}'
        )
        user_prompt = f"Context: {context}\n\nText to analyse:\n{text}"

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            faults = data.get("faults", [])
            if not isinstance(faults, list):
                faults = []
            return [
                FaultDescriptionInterpretation(
                    description=str(f.get("description", "")),
                    system_name=f.get("system_name"),
                    fault_code_suggestion=f.get("fault_code_suggestion"),
                    fault_equipment=f.get("fault_equipment"),
                    fault_message=f.get("fault_message"),
                    confidence=_safe_float(f.get("confidence", 0.0)),
                )
                for f in faults
                if f.get("description")
            ]
        except Exception as exc:
            logger.warning("LLM fault description extraction failed: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    #  4.  interpret_isolation_steps
    # ══════════════════════════════════════════════════════════════

    def interpret_isolation_steps(
        self,
        text: str,
        context: str,
    ) -> list[IsolationStepInterpretation]:
        """Extract fault-isolation decision steps from prose text."""
        system_prompt = (
            "You are an S1000D fault-isolation analyst. "
            "Extract all troubleshooting / isolation steps from the text.\n\n"
            "For each step, extract:\n"
            "  - step_number (int, required): sequential step number\n"
            "  - instruction (required): the action to perform\n"
            "  - question: the yes/no diagnostic question if any\n"
            "  - yes_next: step number to go to on 'yes' (null if terminal)\n"
            "  - no_next: step number to go to on 'no' (null if terminal)\n"
            "  - confidence: 0.0–1.0\n\n"
            "Respond with a JSON object:\n"
            '{"steps": [{"step_number": 1, "instruction": "...", '
            '"question": "...", "yes_next": 2, "no_next": 3, '
            '"confidence": 0.9}, ...]}'
        )
        user_prompt = f"Context: {context}\n\nText to analyse:\n{text}"

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            steps = data.get("steps", [])
            if not isinstance(steps, list):
                steps = []
            return [
                IsolationStepInterpretation(
                    step_number=_safe_int(s.get("step_number", i + 1), i + 1),
                    instruction=str(s.get("instruction", "")),
                    question=s.get("question"),
                    yes_next=(
                        _safe_int(s["yes_next"])
                        if s.get("yes_next") is not None
                        else None
                    ),
                    no_next=(
                        _safe_int(s["no_next"])
                        if s.get("no_next") is not None
                        else None
                    ),
                    confidence=_safe_float(s.get("confidence", 0.0)),
                )
                for i, s in enumerate(steps)
                if s.get("instruction")
            ]
        except Exception as exc:
            logger.warning("LLM isolation step extraction failed: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    #  5.  classify_table
    # ══════════════════════════════════════════════════════════════

    def classify_table(
        self,
        table: TableAsset,
    ) -> TableClassification:
        """Classify a table's role within the fault module via LLM."""
        system_prompt = (
            "You are an S1000D technical document analyst. "
            "Classify the following table into one of these roles:\n"
            "  - lru_list: Line Replaceable Unit listing\n"
            "  - sru_list: Shop Replaceable Unit listing\n"
            "  - spares: spare parts list\n"
            "  - support_equipment: support/test equipment\n"
            "  - supplies: consumables / supplies\n"
            "  - fault_code_table: fault code reference table\n"
            "  - general: general-purpose table\n"
            "  - unknown: cannot determine\n\n"
            "Respond with a JSON object:\n"
            '{"role": "lru_list", "confidence": 0.9, '
            '"reasoning": "brief explanation"}'
        )
        user_prompt = _table_summary(table)

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            role_str = str(data.get("role", "unknown"))
            try:
                role = TableType(role_str)
            except ValueError:
                role = TableType.UNKNOWN
            return TableClassification(
                role=role,
                confidence=_safe_float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning("LLM table classification failed: %s", exc)
            return TableClassification(
                role=TableType.UNKNOWN,
                confidence=0.0,
                reasoning=f"LLM call failed: {exc}",
            )

    # ══════════════════════════════════════════════════════════════
    #  6.  extract_lru_sru
    # ══════════════════════════════════════════════════════════════

    def extract_lru_sru(
        self,
        text: str,
    ) -> list[LruSruExtraction]:
        """Extract LRU / SRU item candidates from prose or table text."""
        system_prompt = (
            "You are an S1000D replaceable-unit analyst. "
            "Extract all LRU (Line Replaceable Unit) and SRU (Shop "
            "Replaceable Unit) items from the provided text.\n\n"
            "For each item, extract:\n"
            "  - name (required): full item name\n"
            "  - short_name: abbreviated name if available\n"
            "  - ident_number: part number / identification number\n"
            "  - is_lru: true if LRU, false if SRU\n"
            "  - confidence: 0.0–1.0\n\n"
            "Respond with a JSON object:\n"
            '{"items": [{"name": "...", "short_name": "...", '
            '"ident_number": "...", "is_lru": true, '
            '"confidence": 0.9}, ...]}'
        )
        user_prompt = text

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            items = data.get("items", [])
            if not isinstance(items, list):
                items = []
            return [
                LruSruExtraction(
                    name=str(item.get("name", "")),
                    short_name=item.get("short_name"),
                    ident_number=item.get("ident_number"),
                    is_lru=_safe_bool(item.get("is_lru", True), default=True),
                    confidence=_safe_float(item.get("confidence", 0.0)),
                )
                for item in items
                if item.get("name")
            ]
        except Exception as exc:
            logger.warning("LLM LRU/SRU extraction failed: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    #  7.  correlate_schematic
    # ══════════════════════════════════════════════════════════════

    def correlate_schematic(
        self,
        schematic: SchematicsItem,
        fault_descriptions: list[str],
    ) -> SchematicCorrelation:
        """Correlate a schematic diagram with fault descriptions via LLM."""
        system_prompt = (
            "You are an aerospace schematic analyst. "
            "Given a schematic diagram's metadata and a list of fault "
            "descriptions, determine which fault descriptions are "
            "relevant to the schematic and which components match.\n\n"
            "Respond with a JSON object:\n"
            '{"matched_descriptions": ["fault desc 1", ...], '
            '"matched_components": ["component name", ...], '
            '"confidence": 0.0-1.0, "reasoning": "brief explanation"}'
        )
        schematic_info = [
            f"Page: {schematic.page_number}",
        ]
        if schematic.components:
            comp_names = [c.name for c in schematic.components if c.name]
            schematic_info.append(f"Components: {', '.join(comp_names)}")
        if schematic.image_metadata:
            schematic_info.append(
                f"Image metadata: {json.dumps(schematic.image_metadata)}"
            )

        user_prompt = (
            "Schematic:\n"
            + "\n".join(schematic_info)
            + "\n\nFault descriptions:\n"
            + "\n".join(f"- {d}" for d in fault_descriptions)
        )

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            matched_desc = data.get("matched_descriptions", [])
            matched_comp = data.get("matched_components", [])
            if not isinstance(matched_desc, list):
                matched_desc = []
            if not isinstance(matched_comp, list):
                matched_comp = []
            return SchematicCorrelation(
                matched_descriptions=[str(d) for d in matched_desc],
                matched_components=[str(c) for c in matched_comp],
                confidence=_safe_float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning("LLM schematic correlation failed: %s", exc)
            return SchematicCorrelation(
                matched_descriptions=[],
                matched_components=[],
                confidence=0.0,
                reasoning=f"LLM call failed: {exc}",
            )
