"""Unit tests for ``FaultSchematicCorrelator``.

Two-pass: RULE (component name overlap, page proximity) → LLM fallback.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.models import FigureRef
from fault_mapper.domain.value_objects import SchematicCorrelation

from fault_mapper.application.fault_schematic_correlator import (
    FaultSchematicCorrelator,
)

from tests.conftest import (
    FakeLlmInterpreter,
    FakeRulesEngine,
    make_schematic,
    make_schematic_component,
)


@pytest.fixture
def correlator(
    fake_llm: FakeLlmInterpreter,
    fake_rules: FakeRulesEngine,
) -> FaultSchematicCorrelator:
    return FaultSchematicCorrelator(llm=fake_llm, rules=fake_rules)


class TestDeterministicMatching:
    def test_component_name_overlap_matches(
        self, correlator: FaultSchematicCorrelator,
    ):
        sch = make_schematic(
            components=[make_schematic_component(name="Hydraulic Pump")],
            page_number=5,
        )
        refs = correlator.correlate(
            schematics=[sch],
            fault_descriptions=["The hydraulic pump failed."],
            relevant_pages=[1, 2, 3],
        )
        assert len(refs) == 1
        assert isinstance(refs[0], FigureRef)

    def test_page_proximity_matches(
        self,
        correlator: FaultSchematicCorrelator,
        fake_llm: FakeLlmInterpreter,
    ):
        sch = make_schematic(
            components=[make_schematic_component(name="Unknown Widget")],
            page_number=3,
        )
        refs = correlator.correlate(
            schematics=[sch],
            fault_descriptions=["Unrelated text"],
            relevant_pages=[3, 4, 5],
        )
        # page 3 is in relevant_pages → match
        assert len(refs) == 1
        # LLM not needed for this match
        # (LLM might still be called if deterministic fails first,
        #  but page match happens in the same method before LLM)

    def test_no_deterministic_match_no_descriptions(
        self,
        correlator: FaultSchematicCorrelator,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.correlation_result = SchematicCorrelation(
            matched_descriptions=[], confidence=0.0, reasoning="no match",
        )
        sch = make_schematic(
            components=[make_schematic_component(name="Widget")],
            page_number=99,
        )
        refs = correlator.correlate(
            schematics=[sch],
            fault_descriptions=[],
            relevant_pages=[1],
        )
        assert len(refs) == 0


class TestLlmFallback:
    def test_llm_above_threshold_matches(
        self,
        correlator: FaultSchematicCorrelator,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.threshold_value = 0.70
        fake_llm.correlation_result = SchematicCorrelation(
            matched_descriptions=["pressure drop"],
            matched_components=["valve"],
            confidence=0.85,
            reasoning="semantically related",
        )
        sch = make_schematic(
            components=[make_schematic_component(name="UniqueXYZ")],
            page_number=99,
        )
        refs = correlator.correlate(
            schematics=[sch],
            fault_descriptions=["pressure drop in valve"],
            relevant_pages=[1],
        )
        assert len(refs) == 1

    def test_llm_below_threshold_no_match(
        self,
        correlator: FaultSchematicCorrelator,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.threshold_value = 0.80
        fake_llm.correlation_result = SchematicCorrelation(
            matched_descriptions=["something"],
            matched_components=[],
            confidence=0.50,
            reasoning="uncertain",
        )
        sch = make_schematic(
            components=[make_schematic_component(name="UniqueABC")],
            page_number=99,
        )
        refs = correlator.correlate(
            schematics=[sch],
            fault_descriptions=["something"],
            relevant_pages=[1],
        )
        assert len(refs) == 0


class TestEdgeCases:
    def test_empty_schematics(self, correlator: FaultSchematicCorrelator):
        refs = correlator.correlate(
            schematics=[],
            fault_descriptions=["fault"],
            relevant_pages=[1],
        )
        assert refs == []

    def test_figure_ref_uses_schematic_id(
        self, correlator: FaultSchematicCorrelator,
    ):
        sch = make_schematic(
            id="sch-42",
            components=[make_schematic_component(name="Pump")],
            page_number=10,
        )
        refs = correlator.correlate(
            schematics=[sch],
            fault_descriptions=["The pump overheated."],
            relevant_pages=[],
        )
        assert len(refs) == 1
        assert refs[0].figure_id == "sch-42"

    def test_figure_ref_falls_back_to_source_path(
        self, correlator: FaultSchematicCorrelator,
    ):
        sch = make_schematic(
            id=None,
            source_path="/path/sch.png",
            components=[make_schematic_component(name="Motor")],
        )
        refs = correlator.correlate(
            schematics=[sch],
            fault_descriptions=["Motor failure noted."],
            relevant_pages=[],
        )
        assert len(refs) == 1
        assert refs[0].figure_id == "/path/sch.png"
