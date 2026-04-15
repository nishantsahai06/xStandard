"""Fault isolation mapper — converts pipeline sections into
``FaultIsolationContent``.

Responsible for:
  • interpreting isolation procedure text via LLM into flat steps
  • wiring steps into a yes/no decision tree using LLM branch hints
  • extracting table-based ``IsolationResult`` for terminal branches

Design decision: ``Section`` has no ``children`` field.  Tree structure
is derived entirely from LLM-interpreted step hints (``yes_next`` /
``no_next``) within each section.  Each section produces an independent
isolation sub-tree.

All helpers shared with the reporting mapper live in
``_shared_helpers``; this file contains only isolation-specific logic.

Strategy tags per block:
  DIRECT — copied verbatim from the source.
  RULE   — deterministic, coded transformation.
  LLM    — semantic interpretation, always gated by threshold.
"""

from __future__ import annotations

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.models import (
    FaultIsolationContent,
    IsolationResult,
    IsolationStep,
    IsolationStepBranch,
    Lru,
    Section,
    TableAsset,
)
from fault_mapper.domain.ports import LlmInterpreterPort, RulesEnginePort
from fault_mapper.domain.value_objects import (
    FieldOrigin,
    IsolationStepInterpretation,
    LruSruExtraction,
)

from fault_mapper.application._shared_helpers import (
    build_common_info,
    collect_tables,
    extraction_to_lru,
    split_extractions,
    table_to_text,
)


class FaultIsolationMapper:
    """Maps pipeline ``Section`` objects into ``FaultIsolationContent``.

    Constructor-injected dependencies:
      ``llm``   — semantic interpretation for step extraction.
      ``rules`` — deterministic mapping rules and thresholds.
    """

    def __init__(
        self,
        llm: LlmInterpreterPort,
        rules: RulesEnginePort,
    ) -> None:
        self._llm = llm
        self._rules = rules

    # ── Public API ───────────────────────────────────────────────

    def map(
        self,
        sections: list[Section],
        origins: dict[str, FieldOrigin],
    ) -> tuple[FaultIsolationContent, dict[str, FieldOrigin]]:
        """Build ``FaultIsolationContent`` from fault-relevant sections.

        Each section produces an independent isolation sub-tree.
        Steps are extracted by the LLM and wired into yes/no branches
        using the LLM's ``yes_next`` / ``no_next`` hints.

        Returns
        -------
        tuple[FaultIsolationContent, dict[str, FieldOrigin]]
            The content block and the updated provenance map.
        """
        all_steps: list[IsolationStep] = []

        for section in sections:
            steps = self._section_to_steps(section, origins)
            all_steps.extend(steps)

        # RULE: shared introductory info from section chunks
        common_info = build_common_info(sections)

        content = FaultIsolationContent(
            fault_isolation_steps=all_steps,
            common_info=common_info,
        )

        origins["faultIsolation.faultIsolationSteps"] = FieldOrigin(
            strategy=MappingStrategy.RULE,
            source_path="sections[*]",
        )
        return content, origins

    # ── Section → isolation steps ────────────────────────────────

    def _section_to_steps(
        self,
        section: Section,
        origins: dict[str, FieldOrigin],
    ) -> list[IsolationStep]:
        """Convert one ``Section`` into isolation steps.

        The LLM extracts a flat list of ``IsolationStepInterpretation``
        objects, each with optional ``yes_next`` / ``no_next``
        step-number hints.  ``_wire_steps`` assembles these into the
        recursive ``IsolationStep`` → ``IsolationStepBranch`` tree
        expected by S1000D.
        """
        # LLM: interpret isolation steps from section text
        interpretations = self._llm.interpret_isolation_steps(
            section.section_text, section.section_title,
        )

        # RULE: threshold gate
        threshold = self._rules.llm_confidence_threshold("isolation_step")
        good = [i for i in interpretations if i.confidence >= threshold]

        if good:
            steps = self._wire_steps(good, section)
            strategy = MappingStrategy.LLM
        else:
            # DIRECT fallback: single non-branching step from section text
            step = IsolationStep(
                step_number=1,
                instruction=(
                    section.section_title
                    or section.section_text[:200]
                ),
                source_chunk_id=section.id,
            )
            steps = [step]
            strategy = MappingStrategy.DIRECT

        origins[f"isolationSteps.{section.id}"] = FieldOrigin(
            strategy=strategy,
            source_path=f"sections[{section.section_order}]",
            source_chunk_id=section.id,
        )

        # RULE: attach table-derived results to terminal steps
        self._attach_table_results(section, steps)

        return steps

    # ── Step wiring ──────────────────────────────────────────────

    @staticmethod
    def _wire_steps(
        interpretations: list[IsolationStepInterpretation],
        section: Section,
    ) -> list[IsolationStep]:
        """LLM+RULE: assemble flat interpretations into a step tree.

        Algorithm:
          1. Build ``IsolationStep`` objects indexed by ``step_number``.
          2. Wire ``yes_group`` / ``no_group`` branches using the
             LLM's ``yes_next`` / ``no_next`` hints.
          3. Root steps are those NOT referenced as a branch target
             by any other step.
        """
        # Build step objects indexed by step_number
        step_map: dict[int, IsolationStep] = {}
        for interp in interpretations:
            step = IsolationStep(
                step_number=interp.step_number,
                instruction=interp.instruction,
                question=interp.question,
                source_chunk_id=section.id,
            )
            step_map[interp.step_number] = step

        # Wire yes/no branches via step-number lookup
        for interp in interpretations:
            step = step_map[interp.step_number]
            if interp.yes_next is not None and interp.yes_next in step_map:
                step.yes_group = IsolationStepBranch(
                    next_steps=[step_map[interp.yes_next]],
                )
            if interp.no_next is not None and interp.no_next in step_map:
                step.no_group = IsolationStepBranch(
                    next_steps=[step_map[interp.no_next]],
                )

        # RULE: roots = steps not referenced as any branch target
        referenced: set[int] = set()
        for interp in interpretations:
            if interp.yes_next is not None:
                referenced.add(interp.yes_next)
            if interp.no_next is not None:
                referenced.add(interp.no_next)

        roots = [
            step_map[i.step_number]
            for i in interpretations
            if i.step_number not in referenced
        ]

        # Fallback: if all steps are referenced, return the first
        return roots if roots else [step_map[interpretations[0].step_number]]

    # ── Table-derived isolation results ──────────────────────────

    def _attach_table_results(
        self,
        section: Section,
        steps: list[IsolationStep],
    ) -> None:
        """RULE+LLM: extract LRU from tables, attach to terminal steps.

        If the section has tables containing LRU data, an
        ``IsolationResult`` is created and attached to the last step.
        For branching steps, the result goes into a ``yes_group``
        branch.  For non-branching steps, the ``decision`` field is
        populated.
        """
        tables = collect_tables([section])
        if not tables:
            return

        extractions = self._extract_lru_sru(tables)
        if not extractions:
            return

        lru_exts, _ = split_extractions(extractions)
        faulty_item: Lru | None = (
            extraction_to_lru(lru_exts[0]) if lru_exts else None
        )

        result = IsolationResult(
            fault_confirmed=faulty_item is not None,
            faulty_item=faulty_item,
        )

        # Attach to the last step (simplest S1000D convention)
        if steps:
            last = steps[-1]
            if last.question and last.yes_group is None:
                last.yes_group = IsolationStepBranch(result=result)
            elif not last.question:
                last.decision = (
                    f"Faulty item: {faulty_item.name}"
                    if faulty_item
                    else "No faulty item identified"
                )

    # ── LRU / SRU extraction ─────────────────────────────────────

    def _extract_lru_sru(
        self,
        tables: list[TableAsset],
    ) -> list[LruSruExtraction]:
        """LLM: run extraction on concatenated table text.

        Returns the full list from ``extract_lru_sru`` — caller
        splits by ``is_lru`` flag as needed.
        """
        combined = "\n---\n".join(table_to_text(t) for t in tables)
        return self._llm.extract_lru_sru(combined)
