"""Fault reporting mapper — converts pipeline sections into
``FaultReportingContent``.

Responsible for:
  • building ``FaultEntry`` lists from fault-relevant sections
  • constructing ``FaultDescription``, ``DetectionInfo``,
    ``LocateAndRepair`` sub-trees
  • correlating schematics via ``FaultSchematicCorrelator``
    (resulting ``FigureRef`` instances go into ``CommonInfo.figures``)

All helpers shared with the isolation mapper live in
``_shared_helpers``; this file contains only reporting-specific logic.

Strategy tags per block:
  DIRECT — copied verbatim from the source.
  RULE   — deterministic, coded transformation.
  LLM    — semantic interpretation, always gated by threshold.
"""

from __future__ import annotations

from fault_mapper.domain.enums import (
    FaultEntryType,
    MappingStrategy,
    TableType,
)
from fault_mapper.domain.models import (
    CommonInfo,
    DetectedLruItem,
    DetectedSruItem,
    DetailedFaultDescription,
    DetectionInfo,
    FaultDescription,
    FaultEntry,
    FaultReportingContent,
    LocateAndRepair,
    LocateAndRepairLruItem,
    LocateAndRepairSruItem,
    Lru,
    Repair,
    SchematicsItem,
    Section,
    Sru,
    TableAsset,
)
from fault_mapper.domain.ports import LlmInterpreterPort, RulesEnginePort
from fault_mapper.domain.value_objects import (
    FieldOrigin,
    LruSruExtraction,
    TableClassification,
)

from fault_mapper.application._shared_helpers import (
    build_common_info,
    collect_pages,
    collect_tables,
    deduplicate_lru_sru,
    extraction_to_lru,
    extraction_to_sru,
    split_extractions,
    table_to_text,
)
from fault_mapper.application.fault_schematic_correlator import (
    FaultSchematicCorrelator,
)
from fault_mapper.application.fault_table_classifier import (
    FaultTableClassifier,
)


class FaultReportingMapper:
    """Maps pipeline ``Section`` objects into ``FaultReportingContent``.

    Constructor-injected dependencies:
      ``llm``                 — semantic extraction fallback.
      ``rules``               — deterministic mapping rules.
      ``table_classifier``    — classifies tables by S1000D type.
      ``schematic_correlator``— links schematics to faults.
    """

    def __init__(
        self,
        llm: LlmInterpreterPort,
        rules: RulesEnginePort,
        table_classifier: FaultTableClassifier,
        schematic_correlator: FaultSchematicCorrelator,
    ) -> None:
        self._llm = llm
        self._rules = rules
        self._table_cls = table_classifier
        self._correlator = schematic_correlator

    # ── Public API ───────────────────────────────────────────────

    def map(
        self,
        sections: list[Section],
        origins: dict[str, FieldOrigin],
        schematics: list[SchematicsItem] | None = None,
    ) -> tuple[FaultReportingContent, dict[str, FieldOrigin]]:
        """Build ``FaultReportingContent`` from fault-relevant sections.

        Parameters
        ----------
        sections
            Fault-relevant sections selected by the section selector.
        origins
            Mutable provenance map — populated by this method.
        schematics
            Document-level schematics from ``DocumentPipelineOutput``.

        Returns
        -------
        tuple[FaultReportingContent, dict[str, FieldOrigin]]
            The content block and the updated provenance map.
        """
        # RULE: one FaultEntry per section
        all_entries: list[FaultEntry] = []
        for section in sections:
            entries = self._section_to_entries(section, origins)
            all_entries.extend(entries)

        # RULE: build common info from section chunks
        common_info = build_common_info(sections)

        # RULE: correlate schematics → CommonInfo.figures
        if schematics and common_info is not None:
            descriptions = self._plain_descriptions(all_entries)
            pages = collect_pages(sections)
            figure_refs = self._correlator.correlate(
                schematics, descriptions, pages,
            )
            common_info.figures.extend(figure_refs)

        content = FaultReportingContent(
            fault_entries=all_entries,
            common_info=common_info,
        )

        origins["faultReporting.faultEntries"] = FieldOrigin(
            strategy=MappingStrategy.RULE,
            source_path="sections[*]",
        )
        return content, origins

    # ── Section → entries ────────────────────────────────────────

    def _section_to_entries(
        self,
        section: Section,
        origins: dict[str, FieldOrigin],
    ) -> list[FaultEntry]:
        """Convert one pipeline ``Section`` into ``FaultEntry`` objects.

        Produces one entry per section.  If the section has classifiable
        tables, LRU/SRU data populates ``detection_info`` and
        ``locate_and_repair``.  Otherwise a text-only entry is created.
        """
        tables = collect_tables([section])
        classified = self._table_cls.classify_all(tables)

        # RULE: split tables by classified role
        detection_tables: list[tuple[TableAsset, TableClassification]] = []
        repair_tables: list[tuple[TableAsset, TableClassification]] = []
        for idx, table in enumerate(tables):
            key = table.id or f"table_{idx}"
            cls = classified.get(key)
            if cls is None:
                continue
            if cls.role == TableType.FAULT_CODE_TABLE:
                detection_tables.append((table, cls))
            elif cls.role in (TableType.LRU_LIST, TableType.SRU_LIST):
                repair_tables.append((table, cls))

        # LLM: extract LRU/SRU from relevant tables
        extractions = self._extract_all(repair_tables + detection_tables)

        if extractions:
            return [self._entry_from_extractions(
                section, extractions, origins,
            )]

        # DIRECT fallback: text-only entry
        return [self._entry_from_text(section, origins)]

    # ── LRU / SRU extraction ─────────────────────────────────────

    def _extract_all(
        self,
        table_pairs: list[tuple[TableAsset, TableClassification]],
    ) -> list[LruSruExtraction]:
        """LLM: run extraction for each (table, classification) pair.

        ``extract_lru_sru`` returns ``list[LruSruExtraction]`` (one VO
        per candidate item, flagged ``is_lru``).
        """
        all_ext: list[LruSruExtraction] = []
        for table, _ in table_pairs:
            text = table_to_text(table)
            exts = self._llm.extract_lru_sru(text)
            all_ext.extend(exts)
        return deduplicate_lru_sru(all_ext)

    # ── Build fault entry from extractions ────────────────────────

    def _entry_from_extractions(
        self,
        section: Section,
        extractions: list[LruSruExtraction],
        origins: dict[str, FieldOrigin],
    ) -> FaultEntry:
        """Build one ``FaultEntry`` with LRU/SRU from table extractions.

        All LRUs and SRUs from this section's tables are collected
        into a single entry's ``detection_info`` and
        ``locate_and_repair``, matching S1000D nesting conventions.
        """
        # RULE: split extractions by is_lru flag
        lru_exts, sru_exts = split_extractions(extractions)
        lru_list = [extraction_to_lru(e) for e in lru_exts]
        sru_list = [extraction_to_sru(e) for e in sru_exts]

        # LLM+RULE: build fault description
        fault_desc, fault_code_hint = self._build_fault_description(
            section, origins,
        )

        # RULE: derive fault code
        fault_code = fault_code_hint or self._rules.derive_fault_code(
            section.section_title, "",
        )

        # RULE: build detection and repair sub-trees
        detection = self._build_detection_info(lru_list, sru_list)
        locate_repair = self._build_locate_and_repair(lru_list, sru_list)

        return FaultEntry(
            entry_type=FaultEntryType.DETECTED_FAULT,
            id=f"fe-{section.id or 'anon'}-000",
            fault_code=fault_code,
            fault_descr=fault_desc,
            detection_info=detection,
            locate_and_repair=locate_repair,
        )

    # ── Fault description ────────────────────────────────────────

    def _build_fault_description(
        self,
        section: Section,
        origins: dict[str, FieldOrigin],
    ) -> tuple[FaultDescription, str | None]:
        """LLM+RULE: build the ``FaultDescription`` sub-tree.

        Returns
        -------
        tuple[FaultDescription, str | None]
            The description and an optional fault-code suggestion
            from the LLM interpretation.
        """
        # LLM: interpret description semantics
        # Port returns list[FaultDescriptionInterpretation]
        interpretations = self._llm.interpret_fault_descriptions(
            section.section_text, section.section_title,
        )

        # RULE: threshold gate — pick first above-threshold interpretation
        threshold = self._rules.llm_confidence_threshold("fault_description")
        interp = next(
            (i for i in interpretations if i.confidence >= threshold),
            None,
        )

        if interp is not None:
            # LLM: map interpretation fields → S1000D detail sub-fields
            has_detail = any([
                interp.system_name,
                interp.fault_equipment,
                interp.fault_message,
            ])
            detailed = DetailedFaultDescription(
                system_name=interp.system_name,
                fault_equip=interp.fault_equipment,
                fault_message_body=interp.fault_message,
            ) if has_detail else None

            fault_desc = FaultDescription(
                descr=interp.description,
                detailed=detailed,
            )
            fault_code_hint = interp.fault_code_suggestion
            strategy = MappingStrategy.LLM
        else:
            # DIRECT fallback: raw section title as description
            fault_desc = FaultDescription(
                descr=section.section_title or "(no description)",
            )
            fault_code_hint = None
            strategy = MappingStrategy.DIRECT

        origins[f"faultDescr.{section.id}"] = FieldOrigin(
            strategy=strategy,
            source_path=f"sections[{section.section_order}]",
            source_chunk_id=section.id,
        )

        return fault_desc, fault_code_hint

    # ── Detection info ───────────────────────────────────────────

    @staticmethod
    def _build_detection_info(
        lru_list: list[Lru],
        sru_list: list[Sru],
    ) -> DetectionInfo | None:
        """RULE: build ``DetectionInfo`` from extracted LRU/SRU lists.

        S1000D nesting: SRUs are nested inside ``DetectedLruItem``.
        """
        if not lru_list and not sru_list:
            return None

        sru_item = (
            DetectedSruItem(srus=sru_list) if sru_list else None
        )
        lru_item = DetectedLruItem(
            lrus=lru_list,
            detected_sru_item=sru_item,
        )
        return DetectionInfo(detected_lru_item=lru_item)

    # ── Locate and repair ────────────────────────────────────────

    @staticmethod
    def _build_locate_and_repair(
        lru_list: list[Lru],
        sru_list: list[Sru],
    ) -> LocateAndRepair | None:
        """RULE: build ``LocateAndRepair`` from extracted LRU/SRU lists.

        S1000D nesting: SRUs nest inside ``LocateAndRepairLruItem``.
        """
        if not lru_list and not sru_list:
            return None

        sru_item = (
            LocateAndRepairSruItem(srus=sru_list, repair=Repair())
            if sru_list else None
        )
        lru_item = LocateAndRepairLruItem(
            lrus=lru_list,
            repair=Repair(),
            locate_and_repair_sru_item=sru_item,
        )
        return LocateAndRepair(locate_and_repair_lru_item=lru_item)

    # ── Text-only fallback ───────────────────────────────────────

    def _entry_from_text(
        self,
        section: Section,
        origins: dict[str, FieldOrigin],
    ) -> FaultEntry:
        """DIRECT fallback: single entry from section text when no tables."""
        fault_desc = FaultDescription(
            descr=section.section_title or "(no description)",
        )
        fault_code = self._rules.derive_fault_code(
            section.section_title, "",
        )

        origins[f"faultDescr.{section.id}.fallback"] = FieldOrigin(
            strategy=MappingStrategy.DIRECT,
            source_path=f"sections[{section.section_order}].section_text",
            source_chunk_id=section.id,
        )

        return FaultEntry(
            entry_type=FaultEntryType.DETECTED_FAULT,
            id=f"fe-{section.id or 'anon'}-000",
            fault_code=fault_code,
            fault_descr=fault_desc,
        )

    # ── Helper collectors ────────────────────────────────────────

    @staticmethod
    def _plain_descriptions(entries: list[FaultEntry]) -> list[str]:
        """Flatten fault entries into plain-text descriptions."""
        texts: list[str] = []
        for entry in entries:
            if entry.fault_descr:
                texts.append(entry.fault_descr.descr)
        return texts
