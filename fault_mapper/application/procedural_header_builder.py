"""Procedural header builder — deterministic DM header construction.

Every header field is derived via **DIRECT** copy or **RULE**-based
generation.  No LLM involvement — this service is fully auditable
and reproducible.

Mirrors ``FaultHeaderBuilder`` structurally.
"""

from __future__ import annotations

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.models import DocumentPipelineOutput
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import ProceduralHeader
from fault_mapper.domain.procedural_ports import ProceduralRulesEnginePort
from fault_mapper.domain.value_objects import FieldOrigin


class ProceduralHeaderBuilder:
    """Builds ``ProceduralHeader`` from source metadata + rules.

    Constructor-injected dependencies:
      ``rules`` — DM-code construction, title normalisation, date /
                  issue resolution, language defaults.
    """

    def __init__(self, rules: ProceduralRulesEnginePort) -> None:
        self._rules = rules

    def build(
        self,
        source: DocumentPipelineOutput,
        module_type: ProceduralModuleType,
    ) -> tuple[ProceduralHeader, dict[str, FieldOrigin]]:
        """Construct the full DM header and return per-field provenance.

        Returns
        -------
        tuple[ProceduralHeader, dict[str, FieldOrigin]]
            The assembled header and a map of field-path → origin.
        """
        origins: dict[str, FieldOrigin] = {}

        # ── RULE: data module code ───────────────────────────────
        dm_code = self._rules.build_dm_code(source, module_type)
        origins["header.dm_code"] = FieldOrigin(
            strategy=MappingStrategy.RULE,
            source_path="source.metadata + config.dm_code_rules",
            confidence=1.0,
        )

        # ── RULE: language ───────────────────────────────────────
        language = self._rules.default_language()
        origins["header.language"] = FieldOrigin(
            strategy=MappingStrategy.RULE,
            source_path="config.default_language",
            confidence=1.0,
        )

        # ── RULE: issue info ─────────────────────────────────────
        issue_info = self._rules.resolve_issue_info()
        origins["header.issue_info"] = FieldOrigin(
            strategy=MappingStrategy.RULE,
            source_path="config.issue_info",
            confidence=1.0,
        )

        # ── RULE: issue date ─────────────────────────────────────
        issue_date = self._rules.resolve_issue_date()
        origins["header.issue_date"] = FieldOrigin(
            strategy=MappingStrategy.RULE,
            source_path="config.issue_date",
            confidence=1.0,
        )

        # ── RULE: title normalisation ────────────────────────────
        raw_title = source.file_name
        dm_title = self._rules.normalize_title(raw_title, module_type)
        origins["header.dm_title"] = FieldOrigin(
            strategy=MappingStrategy.RULE,
            source_path="source.file_name",
            confidence=1.0,
        )

        header = ProceduralHeader(
            dm_code=dm_code,
            language=language,
            issue_info=issue_info,
            issue_date=issue_date,
            dm_title=dm_title,
        )
        return header, origins
