"""Unit tests for ``ProceduralStepExtractor``.

LLM-based extraction + confidence filtering + sub-step wiring.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.procedural_enums import ActionType
from fault_mapper.domain.procedural_value_objects import StepInterpretation

from fault_mapper.application.procedural_step_extractor import (
    ProceduralStepExtractor,
)

from tests.conftest import (
    FakeProceduralLlmInterpreter,
    FakeProceduralRulesEngine,
    make_section,
)


@pytest.fixture
def extractor(
    fake_procedural_rules: FakeProceduralRulesEngine,
    fake_procedural_llm: FakeProceduralLlmInterpreter,
) -> ProceduralStepExtractor:
    return ProceduralStepExtractor(
        rules=fake_procedural_rules,
        llm=fake_procedural_llm,
    )


class TestBasicExtraction:
    def test_extracts_steps_from_llm(
        self,
        extractor: ProceduralStepExtractor,
    ):
        section = make_section(
            section_text="1. Remove panel. 2. Inspect line.",
            id="s1",
        )
        steps, origins = extractor.extract(section, {})

        assert len(steps) >= 1
        assert all(s.text for s in steps)

    def test_step_origins_are_llm(
        self,
        extractor: ProceduralStepExtractor,
    ):
        section = make_section(id="s1")
        steps, origins = extractor.extract(section, {})

        for key, origin in origins.items():
            assert origin.strategy == MappingStrategy.LLM

    def test_step_ids_generated(
        self,
        extractor: ProceduralStepExtractor,
    ):
        section = make_section(id="s1")
        steps, _ = extractor.extract(section, {})
        assert all(s.step_id is not None for s in steps)

    def test_action_type_preserved(
        self,
        extractor: ProceduralStepExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.step_results = [
            StepInterpretation(
                step_number="1",
                text="Torque the bolt to 25 Nm.",
                action_type=ActionType.TORQUE,
                confidence=0.95,
            ),
        ]
        section = make_section(id="s1")
        steps, _ = extractor.extract(section, {})
        assert steps[0].action_type == ActionType.TORQUE


class TestConfidenceFiltering:
    def test_below_threshold_filtered(
        self,
        extractor: ProceduralStepExtractor,
        fake_procedural_rules: FakeProceduralRulesEngine,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_rules.threshold_value = 0.80
        fake_procedural_llm.step_results = [
            StepInterpretation(
                step_number="1",
                text="Good step",
                confidence=0.90,
            ),
            StepInterpretation(
                step_number="2",
                text="Bad step",
                confidence=0.50,
            ),
        ]
        section = make_section(id="s1")
        steps, _ = extractor.extract(section, {})
        assert len(steps) == 1
        assert steps[0].text == "Good step"


class TestSubStepWiring:
    def test_sub_steps_nested_under_parent(
        self,
        extractor: ProceduralStepExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.step_results = [
            StepInterpretation(
                step_number="1", text="Parent step", confidence=0.95,
            ),
            StepInterpretation(
                step_number="1.a", text="Sub-step A", confidence=0.90,
            ),
            StepInterpretation(
                step_number="1.b", text="Sub-step B", confidence=0.90,
            ),
            StepInterpretation(
                step_number="2", text="Second parent", confidence=0.95,
            ),
        ]
        section = make_section(id="s1")
        steps, _ = extractor.extract(section, {})

        # Should have 2 top-level steps
        assert len(steps) == 2
        # First parent should have 2 sub-steps
        assert len(steps[0].sub_steps) == 2
        assert steps[0].sub_steps[0].text == "Sub-step A"


class TestNoticeFlags:
    def test_warning_flag_creates_notice(
        self,
        extractor: ProceduralStepExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.step_results = [
            StepInterpretation(
                step_number="1",
                text="Handle with care",
                has_warning=True,
                has_caution=True,
                has_note=True,
                confidence=0.95,
            ),
        ]
        section = make_section(id="s1")
        steps, _ = extractor.extract(section, {})

        assert len(steps[0].warnings) == 1
        assert len(steps[0].cautions) == 1
        assert len(steps[0].notes) == 1


class TestSourceChunkIds:
    def test_source_chunk_ids_populated(
        self,
        extractor: ProceduralStepExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.step_results = [
            StepInterpretation(
                step_number="1", text="A step", confidence=0.95,
            ),
        ]
        section = make_section(id="s1")
        steps, _ = extractor.extract(section, {})
        assert "s1" in steps[0].source_chunk_ids

    def test_no_id_section_produces_empty_chunk_ids(
        self,
        extractor: ProceduralStepExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.step_results = [
            StepInterpretation(
                step_number="1", text="A step", confidence=0.95,
            ),
        ]
        section = make_section(id=None)
        steps, _ = extractor.extract(section, {})
        assert steps[0].source_chunk_ids == []
