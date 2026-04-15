"""Unit tests for ``FaultSectionSelector``.

Two-pass service: RULE (keyword + section-type) → LLM fallback.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.value_objects import FaultRelevanceAssessment

from fault_mapper.application.fault_section_selector import FaultSectionSelector

from tests.conftest import (
    FakeLlmInterpreter,
    FakeRulesEngine,
    make_section,
    make_source,
)


@pytest.fixture
def selector(
    fake_rules: FakeRulesEngine,
    fake_llm: FakeLlmInterpreter,
) -> FaultSectionSelector:
    return FaultSectionSelector(rules=fake_rules, llm=fake_llm)


class TestRulePass:
    """Section type allow-list and keyword matching — no LLM needed."""

    def test_section_type_match_selects_section(
        self, selector: FaultSectionSelector, fake_llm: FakeLlmInterpreter,
    ):
        source = make_source(sections=[
            make_section(section_type="fault_reporting", id="s1"),
        ])
        sections, origins = selector.select(source)

        assert len(sections) == 1
        assert origins["s1"].strategy == MappingStrategy.RULE
        assert origins["s1"].confidence == 1.0
        # LLM should NOT have been called
        assert len(fake_llm.calls["assess_fault_relevance"]) == 0

    def test_keyword_match_in_title(
        self, selector: FaultSectionSelector,
    ):
        source = make_source(sections=[
            make_section(
                section_title="Troubleshoot Procedure",
                section_type="general",
                id="s1",
            ),
        ])
        sections, origins = selector.select(source)
        assert len(sections) == 1
        assert origins["s1"].strategy == MappingStrategy.RULE

    def test_keyword_match_in_text(
        self, selector: FaultSectionSelector,
    ):
        source = make_source(sections=[
            make_section(
                section_title="Misc",
                section_type="general",
                section_text="This section describes the fault condition.",
                id="s1",
            ),
        ])
        sections, _ = selector.select(source)
        assert len(sections) == 1

    def test_no_match_does_not_select(
        self, selector: FaultSectionSelector, fake_llm: FakeLlmInterpreter,
    ):
        # No keywords, non-matching type, LLM says not relevant
        fake_llm.relevance_result = FaultRelevanceAssessment(
            is_relevant=False, confidence=0.3, reasoning="not relevant",
        )
        source = make_source(sections=[
            make_section(
                section_title="Preface",
                section_type="preface",
                section_text="Welcome to this manual.",
                id="s1",
            ),
        ])
        sections, origins = selector.select(source)
        assert len(sections) == 0


class TestLlmFallback:
    """LLM fallback when rules are inconclusive."""

    def test_llm_above_threshold_selects(
        self, selector: FaultSectionSelector, fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.relevance_result = FaultRelevanceAssessment(
            is_relevant=True, confidence=0.95, reasoning="looks faultish",
        )
        source = make_source(sections=[
            make_section(
                section_title="Ambiguous Section",
                section_type="general",
                section_text="Something about diagnostics.",
                id="s1",
            ),
        ])
        sections, origins = selector.select(source)
        assert len(sections) == 1
        assert origins["s1"].strategy == MappingStrategy.LLM
        assert origins["s1"].confidence == 0.95

    def test_llm_below_threshold_rejects(
        self,
        selector: FaultSectionSelector,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.threshold_value = 0.80
        fake_llm.relevance_result = FaultRelevanceAssessment(
            is_relevant=True, confidence=0.50, reasoning="maybe",
        )
        source = make_source(sections=[
            make_section(
                section_title="Unclear",
                section_type="general",
                section_text="Maybe about testing procedures.",
                id="s1",
            ),
        ])
        sections, _ = selector.select(source)
        assert len(sections) == 0

    def test_llm_not_relevant_rejects(
        self, selector: FaultSectionSelector, fake_llm: FakeLlmInterpreter,
    ):
        fake_llm.relevance_result = FaultRelevanceAssessment(
            is_relevant=False, confidence=0.90, reasoning="no faults here",
        )
        source = make_source(sections=[
            make_section(
                section_title="Random",
                section_type="other",
                section_text="No relevant keywords here at all.",
                id="s1",
            ),
        ])
        sections, _ = selector.select(source)
        assert len(sections) == 0


class TestMixedSections:
    def test_preserves_original_order(
        self, selector: FaultSectionSelector,
    ):
        source = make_source(sections=[
            make_section(section_title="A", section_type="general",
                         section_text="No keywords", id="s1"),
            make_section(section_title="B", section_type="fault_reporting",
                         id="s2"),
            make_section(section_title="C", section_type="troubleshooting",
                         id="s3"),
        ])
        sections, origins = selector.select(source)
        ids = [s.id for s in sections]
        # s1 goes to LLM (default fake says relevant), s2 & s3 match types
        assert "s2" in ids
        assert "s3" in ids

    def test_empty_document_returns_empty(
        self, selector: FaultSectionSelector,
    ):
        source = make_source(sections=[])
        sections, origins = selector.select(source)
        assert sections == []
        assert origins == {}

    def test_section_key_falls_back_to_order(
        self, selector: FaultSectionSelector,
    ):
        source = make_source(sections=[
            make_section(
                section_type="fault_reporting",
                section_order=7,
                id=None,
            ),
        ])
        _, origins = selector.select(source)
        assert "section_7" in origins
