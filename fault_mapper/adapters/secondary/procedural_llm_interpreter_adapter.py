"""Concrete procedural LLM interpreter adapter — implements ``ProceduralLlmInterpreterPort``.

This adapter wraps an OpenAI-compatible chat-completions client and
translates raw LLM JSON responses into the procedural domain
value-object types that the application layer expects.

Critical rules
──────────────
• This adapter NEVER returns target-model instances (ProceduralStep, etc.).
• It returns ONLY intermediate interpretation value objects.
• All prompt engineering lives here — the domain/application layer
  must not contain any LLM prompt text.
• All LLM calls are synchronous from the caller's perspective.
• On parse failure → return a conservative / empty result with
  ``confidence=0.0`` and a ``reasoning`` that explains the failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from fault_mapper.domain.models import Section, TableAsset
from fault_mapper.domain.procedural_enums import (
    ActionType,
    ProceduralSectionType,
)
from fault_mapper.domain.procedural_value_objects import (
    ProceduralRelevanceAssessment,
    ReferenceInterpretation,
    RequirementInterpretation,
    SectionClassificationResult,
    StepInterpretation,
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
    """Extract the text content from an OpenAI-compatible response."""
    try:
        return response.choices[0].message.content  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        pass
    try:
        return response["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        pass
    if isinstance(response, str):
        return response
    raise ValueError(
        f"Cannot extract content from LLM response of type "
        f"{type(response).__name__}"
    )


def _parse_json(raw: str) -> Any:
    """Parse JSON from an LLM response, stripping markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return default


def _section_summary(section: Section, max_chars: int = 2000) -> str:
    """Build a compact text summary of a section for prompts."""
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
    return "\n".join(parts)


def _table_summary(table: TableAsset, max_rows: int = 10) -> str:
    """Build a compact text summary of a table for prompts."""
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


class ProceduralLlmInterpreterAdapter:
    """Adapter that fulfils ``ProceduralLlmInterpreterPort`` via an LLM.

    All 6 port methods are implemented.  Each follows the pattern:
    1. Build a system + user prompt with a JSON output schema.
    2. Call the LLM client.
    3. Parse the JSON response into typed domain value objects.
    4. On parse failure → return a conservative / empty result.
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
    #  1.  assess_procedural_relevance
    # ══════════════════════════════════════════════════════════════

    def assess_procedural_relevance(
        self,
        section: Section,
    ) -> ProceduralRelevanceAssessment:
        """Assess whether a section contains procedural content."""
        system_prompt = (
            "You are an aerospace technical document analyst. "
            "Determine whether the following document section contains "
            "procedural content (maintenance procedures, installation, "
            "removal, servicing, inspection, testing steps, etc.).\n\n"
            "Respond with a JSON object:\n"
            '{"is_relevant": true/false, "confidence": 0.0-1.0, '
            '"reasoning": "brief explanation"}'
        )
        user_prompt = _section_summary(section)

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            return ProceduralRelevanceAssessment(
                is_relevant=_safe_bool(data.get("is_relevant", False)),
                confidence=_safe_float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning(
                "LLM procedural relevance assessment failed: %s", exc,
            )
            return ProceduralRelevanceAssessment(
                is_relevant=False,
                confidence=0.0,
                reasoning=f"LLM call failed: {exc}",
            )

    # ══════════════════════════════════════════════════════════════
    #  2.  classify_section
    # ══════════════════════════════════════════════════════════════

    def classify_section(
        self,
        section: Section,
    ) -> SectionClassificationResult:
        """Classify a section's procedural role via LLM."""
        types_str = ", ".join(f"'{t.value}'" for t in ProceduralSectionType)
        system_prompt = (
            "You are an S1000D technical document analyst. "
            "Classify the following document section into one of "
            f"these procedural types: {types_str}.\n\n"
            "Respond with a JSON object:\n"
            '{"section_type": "<type>", "confidence": 0.0-1.0, '
            '"reasoning": "brief explanation"}'
        )
        user_prompt = _section_summary(section)

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            type_str = str(data.get("section_type", "general"))
            try:
                section_type = ProceduralSectionType(type_str)
            except ValueError:
                section_type = ProceduralSectionType.GENERAL
            return SectionClassificationResult(
                section_type=section_type,
                confidence=_safe_float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning("LLM section classification failed: %s", exc)
            return SectionClassificationResult(
                section_type=ProceduralSectionType.GENERAL,
                confidence=0.0,
                reasoning=f"LLM call failed: {exc}",
            )

    # ══════════════════════════════════════════════════════════════
    #  3.  interpret_procedural_steps
    # ══════════════════════════════════════════════════════════════

    def interpret_procedural_steps(
        self,
        text: str,
        context: str,
    ) -> list[StepInterpretation]:
        """Extract procedural steps from unstructured text."""
        actions_str = ", ".join(f"'{a.value}'" for a in ActionType)
        system_prompt = (
            "You are an S1000D procedural analyst. "
            "Extract all procedural steps from the provided text.\n\n"
            "For each step, extract:\n"
            "  - step_number (required): the original step numbering\n"
            "  - text (required): the instruction text\n"
            f"  - action_type: one of {actions_str}\n"
            "  - expected_result: expected outcome if mentioned\n"
            "  - has_warning: true if step has a warning\n"
            "  - has_caution: true if step has a caution\n"
            "  - has_note: true if step has a note\n"
            "  - sub_step_hints: list of child numbering strings\n"
            "  - confidence: 0.0-1.0\n\n"
            "Respond with a JSON object:\n"
            '{"steps": [{"step_number": "1", "text": "...", '
            '"action_type": "general", "expected_result": null, '
            '"has_warning": false, "has_caution": false, '
            '"has_note": false, "sub_step_hints": [], '
            '"confidence": 0.9}, ...]}'
        )
        user_prompt = f"Context: {context}\n\nText to analyse:\n{text}"

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            steps = data.get("steps", [])
            if not isinstance(steps, list):
                steps = []
            results: list[StepInterpretation] = []
            for s in steps:
                if not s.get("text"):
                    continue
                action_str = str(s.get("action_type", "general"))
                try:
                    action = ActionType(action_str)
                except ValueError:
                    action = ActionType.GENERAL
                hints = s.get("sub_step_hints", [])
                if not isinstance(hints, list):
                    hints = []
                results.append(
                    StepInterpretation(
                        step_number=str(s.get("step_number", "")),
                        text=str(s["text"]),
                        action_type=action,
                        expected_result=s.get("expected_result"),
                        has_warning=_safe_bool(s.get("has_warning")),
                        has_caution=_safe_bool(s.get("has_caution")),
                        has_note=_safe_bool(s.get("has_note")),
                        sub_step_hints=[str(h) for h in hints],
                        confidence=_safe_float(s.get("confidence", 0.0)),
                    ),
                )
            return results
        except Exception as exc:
            logger.warning("LLM procedural step extraction failed: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    #  4.  interpret_requirements
    # ══════════════════════════════════════════════════════════════

    def interpret_requirements(
        self,
        text: str,
        context: str,
    ) -> list[RequirementInterpretation]:
        """Extract preliminary requirements from prose text."""
        system_prompt = (
            "You are an S1000D requirements analyst. "
            "Extract all preliminary requirements (personnel, "
            "equipment, supplies, spares, safety) from the text.\n\n"
            "For each requirement, extract:\n"
            "  - requirement_type (required): 'personnel'|'equipment'"
            "|'supply'|'spare'|'safety'\n"
            "  - name: item or person name\n"
            "  - quantity: numeric quantity\n"
            "  - unit: unit of measure\n"
            "  - role: personnel role\n"
            "  - skill_level: skill level\n"
            "  - ident_number: part/identification number\n"
            "  - safety_text: safety-related text\n"
            "  - confidence: 0.0-1.0\n\n"
            "Respond with a JSON object:\n"
            '{"requirements": [{"requirement_type": "equipment", '
            '"name": "...", "confidence": 0.9}, ...]}'
        )
        user_prompt = f"Context: {context}\n\nText to analyse:\n{text}"

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            reqs = data.get("requirements", [])
            if not isinstance(reqs, list):
                reqs = []
            return [
                RequirementInterpretation(
                    requirement_type=str(
                        r.get("requirement_type", "equipment"),
                    ),
                    name=r.get("name"),
                    quantity=_safe_float(r.get("quantity", 0.0)),
                    unit=r.get("unit"),
                    role=r.get("role"),
                    skill_level=r.get("skill_level"),
                    ident_number=r.get("ident_number"),
                    safety_text=r.get("safety_text"),
                    confidence=_safe_float(r.get("confidence", 0.0)),
                )
                for r in reqs
                if r.get("requirement_type")
            ]
        except Exception as exc:
            logger.warning("LLM requirement extraction failed: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    #  5.  interpret_references
    # ══════════════════════════════════════════════════════════════

    def interpret_references(
        self,
        text: str,
    ) -> list[ReferenceInterpretation]:
        """Extract cross-references from procedural text."""
        system_prompt = (
            "You are an S1000D reference analyst. "
            "Extract all cross-references from the provided text.\n\n"
            "For each reference, extract:\n"
            "  - ref_type (required): 'dm_ref'|'figure_ref'|"
            "'table_ref'|'external'\n"
            "  - target_text (required): the reference text as written\n"
            "  - target_dm_code: DM code if referenced\n"
            "  - target_id: figure/table ID if referenced\n"
            "  - label: display label\n"
            "  - confidence: 0.0-1.0\n\n"
            "Respond with a JSON object:\n"
            '{"references": [{"ref_type": "dm_ref", '
            '"target_text": "...", "confidence": 0.9}, ...]}'
        )
        user_prompt = text

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            refs = data.get("references", [])
            if not isinstance(refs, list):
                refs = []
            return [
                ReferenceInterpretation(
                    ref_type=str(r.get("ref_type", "external")),
                    target_text=str(r.get("target_text", "")),
                    target_dm_code=r.get("target_dm_code"),
                    target_id=r.get("target_id"),
                    label=r.get("label"),
                    confidence=_safe_float(r.get("confidence", 0.0)),
                )
                for r in refs
                if r.get("target_text")
            ]
        except Exception as exc:
            logger.warning("LLM reference extraction failed: %s", exc)
            return []

    # ══════════════════════════════════════════════════════════════
    #  6.  classify_procedural_table
    # ══════════════════════════════════════════════════════════════

    def classify_procedural_table(
        self,
        table: TableAsset,
    ) -> SectionClassificationResult:
        """Classify a table's role within the procedure via LLM."""
        types_str = ", ".join(f"'{t.value}'" for t in ProceduralSectionType)
        system_prompt = (
            "You are an S1000D technical document analyst. "
            "Classify the following table into one of these "
            f"procedural section types: {types_str}.\n\n"
            "Respond with a JSON object:\n"
            '{"section_type": "<type>", "confidence": 0.0-1.0, '
            '"reasoning": "brief explanation"}'
        )
        user_prompt = _table_summary(table)

        try:
            raw = self._call(system_prompt, user_prompt)
            data = _parse_json(raw)
            type_str = str(data.get("section_type", "general"))
            try:
                section_type = ProceduralSectionType(type_str)
            except ValueError:
                section_type = ProceduralSectionType.GENERAL
            return SectionClassificationResult(
                section_type=section_type,
                confidence=_safe_float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
            )
        except Exception as exc:
            logger.warning(
                "LLM procedural table classification failed: %s", exc,
            )
            return SectionClassificationResult(
                section_type=ProceduralSectionType.GENERAL,
                confidence=0.0,
                reasoning=f"LLM call failed: {exc}",
            )
