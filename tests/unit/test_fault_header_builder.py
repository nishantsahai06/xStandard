"""Unit tests for ``FaultHeaderBuilder``.

Pure RULE service — no LLM, all deterministic.  Tests verify that
the builder delegates to the rules engine and wires return values
into the correct ``FaultHeader`` fields with ``RULE`` provenance.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import FaultMode, MappingStrategy
from fault_mapper.domain.models import FaultHeader
from fault_mapper.domain.value_objects import DmTitle

from fault_mapper.application.fault_header_builder import FaultHeaderBuilder

from tests.conftest import (
    FakeRulesEngine,
    make_dm_code,
    make_source,
)


@pytest.fixture
def builder(fake_rules: FakeRulesEngine) -> FaultHeaderBuilder:
    return FaultHeaderBuilder(rules=fake_rules)


class TestFaultHeaderBuilder:
    def test_builds_all_header_fields(
        self, builder: FaultHeaderBuilder, fake_rules: FakeRulesEngine,
    ):
        source = make_source()
        header, origins = builder.build(source, FaultMode.FAULT_REPORTING)

        assert isinstance(header, FaultHeader)
        assert header.dm_code == fake_rules.dm_code_value
        assert header.language == fake_rules.language_value
        assert header.issue_info == fake_rules.issue_info_value
        assert header.issue_date == fake_rules.issue_date_value
        assert header.dm_title == fake_rules.title_value

    def test_all_origins_are_rule(
        self, builder: FaultHeaderBuilder, fake_rules: FakeRulesEngine,
    ):
        source = make_source()
        _, origins = builder.build(source, FaultMode.FAULT_REPORTING)

        assert len(origins) == 5
        for key, origin in origins.items():
            assert origin.strategy == MappingStrategy.RULE
            assert origin.confidence == 1.0

    def test_delegates_to_rules_engine(
        self, builder: FaultHeaderBuilder, fake_rules: FakeRulesEngine,
    ):
        source = make_source()
        builder.build(source, FaultMode.FAULT_ISOLATION)

        assert len(fake_rules.calls["build_dm_code"]) == 1
        assert len(fake_rules.calls["default_language"]) == 1
        assert len(fake_rules.calls["resolve_issue_info"]) == 1
        assert len(fake_rules.calls["resolve_issue_date"]) == 1
        assert len(fake_rules.calls["normalize_title"]) == 1

    def test_passes_mode_to_dm_code_and_title(
        self, builder: FaultHeaderBuilder, fake_rules: FakeRulesEngine,
    ):
        source = make_source()
        builder.build(source, FaultMode.FAULT_ISOLATION)

        _, mode_arg = fake_rules.calls["build_dm_code"][0]
        assert mode_arg is FaultMode.FAULT_ISOLATION

        _, title_mode_arg = fake_rules.calls["normalize_title"][0]
        assert title_mode_arg is FaultMode.FAULT_ISOLATION

    def test_passes_file_name_to_normalize_title(
        self, builder: FaultHeaderBuilder, fake_rules: FakeRulesEngine,
    ):
        source = make_source(file_name="my-doc.pdf")
        builder.build(source, FaultMode.FAULT_REPORTING)

        raw_title, _ = fake_rules.calls["normalize_title"][0]
        assert raw_title == "my-doc.pdf"
