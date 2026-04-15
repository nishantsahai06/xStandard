"""Unit tests for ``ProceduralHeaderBuilder``.

Pure RULE service — no LLM, all deterministic.  Tests verify that
the builder delegates to the rules engine and wires return values
into the correct ``ProceduralHeader`` fields with ``RULE`` provenance.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.procedural_enums import ProceduralModuleType
from fault_mapper.domain.procedural_models import ProceduralHeader

from fault_mapper.application.procedural_header_builder import (
    ProceduralHeaderBuilder,
)

from tests.conftest import (
    FakeProceduralRulesEngine,
    make_source,
)


@pytest.fixture
def builder(
    fake_procedural_rules: FakeProceduralRulesEngine,
) -> ProceduralHeaderBuilder:
    return ProceduralHeaderBuilder(rules=fake_procedural_rules)


class TestProceduralHeaderBuilder:
    def test_builds_all_header_fields(
        self,
        builder: ProceduralHeaderBuilder,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        source = make_source()
        header, origins = builder.build(
            source, ProceduralModuleType.PROCEDURAL,
        )

        assert isinstance(header, ProceduralHeader)
        assert header.dm_code == fake_procedural_rules.dm_code_value
        assert header.language == fake_procedural_rules.language_value
        assert header.issue_info == fake_procedural_rules.issue_info_value
        assert header.issue_date == fake_procedural_rules.issue_date_value
        assert header.dm_title == fake_procedural_rules.title_value

    def test_all_origins_are_rule(
        self,
        builder: ProceduralHeaderBuilder,
    ):
        source = make_source()
        _, origins = builder.build(
            source, ProceduralModuleType.PROCEDURAL,
        )

        assert len(origins) == 5
        for key, origin in origins.items():
            assert origin.strategy == MappingStrategy.RULE
            assert origin.confidence == 1.0

    def test_delegates_to_rules_engine(
        self,
        builder: ProceduralHeaderBuilder,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        source = make_source()
        builder.build(source, ProceduralModuleType.DESCRIPTIVE)

        assert len(fake_procedural_rules.calls["build_dm_code"]) == 1
        assert len(fake_procedural_rules.calls["default_language"]) == 1
        assert len(fake_procedural_rules.calls["resolve_issue_info"]) == 1
        assert len(fake_procedural_rules.calls["resolve_issue_date"]) == 1
        assert len(fake_procedural_rules.calls["normalize_title"]) == 1

    def test_passes_module_type_to_dm_code_and_title(
        self,
        builder: ProceduralHeaderBuilder,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        source = make_source()
        builder.build(source, ProceduralModuleType.DESCRIPTIVE)

        _, module_type_arg = fake_procedural_rules.calls["build_dm_code"][0]
        assert module_type_arg is ProceduralModuleType.DESCRIPTIVE

        _, title_module_type_arg = fake_procedural_rules.calls["normalize_title"][0]
        assert title_module_type_arg is ProceduralModuleType.DESCRIPTIVE

    def test_passes_file_name_to_normalize_title(
        self,
        builder: ProceduralHeaderBuilder,
        fake_procedural_rules: FakeProceduralRulesEngine,
    ):
        source = make_source(file_name="B737-Removal.pdf")
        builder.build(source, ProceduralModuleType.PROCEDURAL)

        raw_title, _ = fake_procedural_rules.calls["normalize_title"][0]
        assert raw_title == "B737-Removal.pdf"
