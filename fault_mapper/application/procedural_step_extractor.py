"""Procedural step extractor — extracts ordered steps from sections.

Core content mapper for the procedural pipeline (analogous to
``FaultReportingMapper`` / ``FaultIsolationMapper``).

Takes a source ``Section`` and returns structured ``ProceduralStep``
objects with sub-step nesting.  Never mutates input models.
"""

from __future__ import annotations

import re

from fault_mapper.domain.enums import MappingStrategy, NoteLikeKind
from fault_mapper.domain.models import NoteLike, Section
from fault_mapper.domain.procedural_models import ProceduralStep
from fault_mapper.domain.procedural_ports import (
    ProceduralLlmInterpreterPort,
    ProceduralRulesEnginePort,
)
from fault_mapper.domain.procedural_value_objects import StepInterpretation
from fault_mapper.domain.value_objects import FieldOrigin


class ProceduralStepExtractor:
    """Extracts and structures procedural steps from source sections.

    Never mutates input ``Section`` objects.
    Returns new ``ProceduralStep`` objects.
    """

    def __init__(
        self,
        rules: ProceduralRulesEnginePort,
        llm: ProceduralLlmInterpreterPort,
    ) -> None:
        self._rules = rules
        self._llm = llm

    # ── Public API ───────────────────────────────────────────────

    def extract(
        self,
        section: Section,
        existing_origins: dict[str, FieldOrigin],
    ) -> tuple[list[ProceduralStep], dict[str, FieldOrigin]]:
        """Extract procedural steps from one source section.

        Pipeline:
          1. LLM interprets steps from section text.
          2. Filter by confidence threshold.
          3. Normalize step numbers via rules.
          4. Convert interpretations to ProceduralStep models.
          5. Extract step-level notices from interpretation flags.
          6. Wire sub-steps from flat list into nested tree.
          7. Build FieldOrigin per step.

        Returns
        -------
        tuple[list[ProceduralStep], dict[str, FieldOrigin]]
            Top-level steps (sub-steps nested inside) + origins.
        """
        threshold = self._rules.llm_confidence_threshold("step_extraction")
        context = section.section_title

        # Step 1: LLM interpretation
        interpretations = self._llm.interpret_procedural_steps(
            section.section_text, context,
        )

        # Step 2: filter by confidence
        accepted = [i for i in interpretations if i.confidence >= threshold]

        # Steps 3-5: convert to models
        flat_steps: list[ProceduralStep] = []
        origins: dict[str, FieldOrigin] = {}

        for interp in accepted:
            step = self._build_step(interp, section)
            flat_steps.append(step)

            key = f"step.{_section_key(section)}.{step.step_number}"
            origins[key] = FieldOrigin(
                strategy=MappingStrategy.LLM,
                source_path=(
                    f"sections[{section.section_order}].section_text"
                ),
                confidence=interp.confidence,
                source_chunk_id=section.id,
            )

        # Step 6: wire sub-steps into nested tree
        top_level = _wire_sub_steps(flat_steps)

        return top_level, origins

    # ── Internals ────────────────────────────────────────────────

    def _build_step(
        self,
        interp: StepInterpretation,
        section: Section,
    ) -> ProceduralStep:
        """Convert one LLM interpretation into a ProceduralStep."""
        step_number = self._rules.normalize_step_number(interp.step_number)

        # Extract notices from interpretation flags
        warnings: list[NoteLike] = []
        cautions: list[NoteLike] = []
        notes: list[NoteLike] = []

        if interp.has_warning:
            warnings.append(NoteLike(
                kind=NoteLikeKind.WARNING,
                text="",  # TODO: Chunk 3+ — extract actual text
            ))
        if interp.has_caution:
            cautions.append(NoteLike(
                kind=NoteLikeKind.CAUTION,
                text="",  # TODO: Chunk 3+ — extract actual text
            ))
        if interp.has_note:
            notes.append(NoteLike(
                kind=NoteLikeKind.NOTE,
                text="",  # TODO: Chunk 3+ — extract actual text
            ))

        return ProceduralStep(
            step_id=f"step-{step_number}",
            step_number=step_number,
            text=interp.text,
            action_type=interp.action_type,
            source_chunk_ids=[section.id] if section.id else [],
            warnings=warnings,
            cautions=cautions,
            notes=notes,
            expected_result=interp.expected_result,
        )


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL HELPERS (pure, no port access)
# ═══════════════════════════════════════════════════════════════════════


def _section_key(section: Section) -> str:
    """Stable key for a section."""
    return section.id or f"section_{section.section_order}"


def _wire_sub_steps(
    flat_steps: list[ProceduralStep],
) -> list[ProceduralStep]:
    """Wire flat steps into a nested tree based on step numbering.

    Nesting heuristic: a step is a sub-step of the preceding
    top-level step if its number contains a dot or letter suffix.

    Examples::

        ["1", "1.a", "1.b", "2", "2.1"] →
          step "1" gets sub_steps ["1.a", "1.b"]
          step "2" gets sub_steps ["2.1"]

    Returns only top-level steps with ``sub_steps`` populated.
    """
    if not flat_steps:
        return []

    top_level: list[ProceduralStep] = []
    current_parent: ProceduralStep | None = None

    for step in flat_steps:
        if _is_sub_step_number(step.step_number):
            if current_parent is not None:
                current_parent.sub_steps.append(step)
            else:
                # No parent found — treat as top-level
                top_level.append(step)
        else:
            current_parent = step
            top_level.append(step)

    return top_level


def _is_sub_step_number(number: str) -> bool:
    """Determine if a step number indicates a sub-step.

    Sub-step indicators:
      - Contains a dot (e.g., "1.a", "2.1")
      - Contains a letter after digits (e.g., "1a", "3b")
      - Starts with a single letter (e.g., "a", "b")
    """
    if "." in number:
        return True
    if re.match(r"^\d+[a-zA-Z]", number):
        return True
    if re.match(r"^[a-zA-Z]$", number):
        return True
    return False
