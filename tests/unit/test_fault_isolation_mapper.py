"""Unit tests for ``FaultIsolationMapper``.

Tests LLM step extraction, yes/no tree wiring, table-based
isolation results, and the DIRECT fallback.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.models import (
    FaultIsolationContent,
    IsolationStep,
    IsolationStepBranch,
)
from fault_mapper.domain.value_objects import (
    FieldOrigin,
    IsolationStepInterpretation,
    LruSruExtraction,
)

from fault_mapper.application.fault_isolation_mapper import FaultIsolationMapper

from tests.conftest import (
    FakeLlmInterpreter,
    FakeRulesEngine,
    make_chunk,
    make_section,
    make_table,
)


@pytest.fixture
def mapper(
    fake_llm: FakeLlmInterpreter,
    fake_rules: FakeRulesEngine,
) -> FaultIsolationMapper:
    return FaultIsolationMapper(llm=fake_llm, rules=fake_rules)


# ═══════════════════════════════════════════════════════════════════════
#  Step extraction and wiring
# ═══════════════════════════════════════════════════════════════════════


class TestStepWiring:
    def test_linear_chain(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        """3 steps: 1→yes→2, 1→no→3.  Steps 2 and 3 are leaves."""
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Check gauge",
                question="Pressure OK?", yes_next=2, no_next=3,
                confidence=0.90,
            ),
            IsolationStepInterpretation(
                step_number=2, instruction="System normal",
                confidence=0.90,
            ),
            IsolationStepInterpretation(
                step_number=3, instruction="Replace pump",
                confidence=0.90,
            ),
        ]

        section = make_section(id="s1", tables=[])
        content, origins = mapper.map([section], {})

        assert isinstance(content, FaultIsolationContent)
        # Only step 1 is a root (2 and 3 are referenced)
        assert len(content.fault_isolation_steps) == 1

        root = content.fault_isolation_steps[0]
        assert root.step_number == 1
        assert root.question == "Pressure OK?"
        assert root.yes_group is not None
        assert root.yes_group.next_steps[0].step_number == 2
        assert root.no_group is not None
        assert root.no_group.next_steps[0].step_number == 3

    def test_single_step_no_branches(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Inspect visually",
                confidence=0.90,
            ),
        ]

        section = make_section(id="s1", tables=[])
        content, _ = mapper.map([section], {})

        assert len(content.fault_isolation_steps) == 1
        step = content.fault_isolation_steps[0]
        assert step.yes_group is None
        assert step.no_group is None

    def test_all_steps_referenced_returns_first(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        """If every step is referenced as a branch target, return the first."""
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Step 1",
                question="Q?", yes_next=2, no_next=None,
                confidence=0.90,
            ),
            IsolationStepInterpretation(
                step_number=2, instruction="Step 2",
                question="Q2?", yes_next=1, no_next=None,
                confidence=0.90,
            ),
        ]

        section = make_section(id="s1", tables=[])
        content, _ = mapper.map([section], {})
        # Both are referenced, fallback returns first
        assert len(content.fault_isolation_steps) == 1
        assert content.fault_isolation_steps[0].step_number == 1


# ═══════════════════════════════════════════════════════════════════════
#  DIRECT fallback
# ═══════════════════════════════════════════════════════════════════════


class TestDirectFallback:
    def test_below_threshold_creates_single_step(
        self,
        mapper: FaultIsolationMapper,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.threshold_value = 0.80
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Low confidence step",
                confidence=0.30,  # below threshold
            ),
        ]

        section = make_section(
            id="s1", section_title="Check Hydraulics", tables=[],
        )
        content, origins = mapper.map([section], {})

        assert len(content.fault_isolation_steps) == 1
        step = content.fault_isolation_steps[0]
        assert step.instruction == "Check Hydraulics"
        assert step.step_number == 1
        assert origins["isolationSteps.s1"].strategy == MappingStrategy.DIRECT

    def test_empty_llm_results_creates_single_step(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.isolation_step_results = []

        section = make_section(
            id="s1", section_title="Visual Inspection", tables=[],
        )
        content, _ = mapper.map([section], {})
        assert len(content.fault_isolation_steps) == 1
        assert content.fault_isolation_steps[0].instruction == "Visual Inspection"


# ═══════════════════════════════════════════════════════════════════════
#  Table-derived isolation results
# ═══════════════════════════════════════════════════════════════════════


class TestTableResults:
    def test_lru_from_table_attached_to_last_step(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Check pump",
                question="Pump working?", yes_next=None, no_next=None,
                confidence=0.90,
            ),
        ]
        fake_llm.lru_sru_results = [
            LruSruExtraction(
                name="Hydraulic Pump", is_lru=True, confidence=0.95,
            ),
        ]

        table = make_table(
            id="t1", headers=["Part"],
            rows=[["Hydraulic Pump"]],
        )
        section = make_section(id="s1", tables=[table])
        content, _ = mapper.map([section], {})

        step = content.fault_isolation_steps[0]
        # Step has a question → result goes in yes_group
        assert step.yes_group is not None
        assert step.yes_group.result is not None
        assert step.yes_group.result.fault_confirmed is True
        assert step.yes_group.result.faulty_item.name == "Hydraulic Pump"

    def test_no_lru_sets_decision_on_non_question_step(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Final step",
                question=None,  # no question
                confidence=0.90,
            ),
        ]
        fake_llm.lru_sru_results = [
            LruSruExtraction(
                name="Pump", is_lru=True, confidence=0.95,
            ),
        ]

        table = make_table(id="t1", headers=["Part"])
        section = make_section(id="s1", tables=[table])
        content, _ = mapper.map([section], {})

        step = content.fault_isolation_steps[0]
        assert step.decision is not None
        assert "Pump" in step.decision

    def test_no_tables_no_result(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Check gauge",
                confidence=0.90,
            ),
        ]

        section = make_section(id="s1", tables=[])
        content, _ = mapper.map([section], {})
        step = content.fault_isolation_steps[0]
        assert step.yes_group is None
        assert step.decision is None


# ═══════════════════════════════════════════════════════════════════════
#  Common info and multi-section
# ═══════════════════════════════════════════════════════════════════════


class TestCommonInfoAndMultiSection:
    def test_common_info_from_sections(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Step 1", confidence=0.90,
            ),
        ]
        section = make_section(
            id="s1",
            section_title="Isolation Intro",
            chunks=[make_chunk(chunk_text="Introduction text")],
            tables=[],
        )
        content, _ = mapper.map([section], {})
        assert content.common_info is not None
        assert content.common_info.title == "Isolation Intro"

    def test_multiple_sections_merge_steps(
        self,
        mapper: FaultIsolationMapper,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.isolation_step_results = [
            IsolationStepInterpretation(
                step_number=1, instruction="Step from section", confidence=0.90,
            ),
        ]
        s1 = make_section(id="s1", tables=[])
        s2 = make_section(id="s2", tables=[])
        content, _ = mapper.map([s1, s2], {})
        # Each section produces steps; both are merged
        assert len(content.fault_isolation_steps) >= 2

    def test_empty_sections_returns_empty_content(
        self,
        mapper: FaultIsolationMapper,
    ):
        content, _ = mapper.map([], {})
        assert content.fault_isolation_steps == []
        assert content.common_info is None
