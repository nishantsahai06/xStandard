"""Unit tests for ``ProceduralDocumentClassifier``.

Two-pass service: RULE (keyword + section-type) → LLM fallback.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.procedural_value_objects import (
    ProceduralRelevanceAssessment,
)

from fault_mapper.application.procedural_document_classifier import (
    ProceduralDocumentClassifier,
)

from tests.conftest import (
    FakeProceduralLlmInterpreter,
    FakeProceduralRulesEngine,
    make_section,
    make_source,
)


@pytest.fixture
def classifier(
    fake_procedural_rules: FakeProceduralRulesEngine,
    fake_procedural_llm: FakeProceduralLlmInterpreter,
) -> ProceduralDocumentClassifier:
    return ProceduralDocumentClassifier(
        rules=fake_procedural_rules,
        llm=fake_procedural_llm,
    )


class TestRulePass:
    """Section type allow-list and keyword matching — no LLM needed."""

    def test_section_type_match_selects_section(
        self,
        classifier: ProceduralDocumentClassifier,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        source = make_source(sections=[
            make_section(section_type="procedure", id="s1"),
        ])
        sections, origins = classifier.classify(source)

        assert len(sections) == 1
        assert origins["s1"].strategy == MappingStrategy.RULE
        assert origins["s1"].confidence == 1.0
        # LLM should NOT have been called
        assert len(fake_procedural_llm.calls["assess_procedural_relevance"]) == 0

    def test_keyword_match_in_title(
        self,
        classifier: ProceduralDocumentClassifier,
    ):
        source = make_source(sections=[
            make_section(
                section_title="Installation Procedure",
                section_type="general",
                id="s1",
            ),
        ])
        sections, origins = classifier.classify(source)
        assert len(sections) == 1
        assert origins["s1"].strategy == MappingStrategy.RULE

    def test_keyword_match_in_text(
        self,
        classifier: ProceduralDocumentClassifier,
    ):
        source = make_source(sections=[
            make_section(
                section_title="Misc",
                section_type="general",
                section_text="Follow this step to remove the panel.",
                id="s1",
            ),
        ])
        sections, _ = classifier.classify(source)
        assert len(sections) == 1

    def test_no_match_does_not_select(
        self,
        classifier: ProceduralDocumentClassifier,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.relevance_result = ProceduralRelevanceAssessment(
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
        sections, origins = classifier.classify(source)
        assert len(sections) == 0


class TestLlmFallback:
    """LLM fallback when rules are inconclusive."""

    def test_llm_above_threshold_selects(
        self,
        classifier: ProceduralDocumentClassifier,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.relevance_result = ProceduralRelevanceAssessment(
            is_relevant=True, confidence=0.95, reasoning="has procedural steps",
        )
        source = make_source(sections=[
            make_section(
                section_title="Ambiguous Section",
                section_type="general",
                section_text="Something about performing work.",
                id="s1",
            ),
        ])
        sections, origins = classifier.classify(source)
        assert len(sections) == 1
        assert origins["s1"].strategy == MappingStrategy.LLM
        assert origins["s1"].confidence == 0.95

    def test_llm_below_threshold_rejects(
        self,
        classifier: ProceduralDocumentClassifier,
        fake_procedural_rules: FakeProceduralRulesEngine,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_rules.threshold_value = 0.80
        fake_procedural_llm.relevance_result = ProceduralRelevanceAssessment(
            is_relevant=True, confidence=0.50, reasoning="maybe",
        )
        source = make_source(sections=[
            make_section(
                section_title="Unclear",
                section_type="general",
                section_text="Some general text without specific keywords.",
                id="s1",
            ),
        ])
        sections, _ = classifier.classify(source)
        assert len(sections) == 0

    def test_llm_not_relevant_rejects(
        self,
        classifier: ProceduralDocumentClassifier,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.relevance_result = ProceduralRelevanceAssessment(
            is_relevant=False, confidence=0.90, reasoning="no procedures",
        )
        source = make_source(sections=[
            make_section(
                section_title="Random",
                section_type="other",
                section_text="No relevant keywords here at all.",
                id="s1",
            ),
        ])
        sections, _ = classifier.classify(source)
        assert len(sections) == 0


class TestMixedSections:
    def test_preserves_original_order(
        self,
        classifier: ProceduralDocumentClassifier,
    ):
        source = make_source(sections=[
            make_section(
                section_title="A", section_type="general",
                section_text="No keywords", id="s1",
            ),
            make_section(
                section_title="B", section_type="procedure", id="s2",
            ),
            make_section(
                section_title="C", section_type="maintenance", id="s3",
            ),
        ])
        sections, origins = classifier.classify(source)
        ids = [s.id for s in sections]
        assert "s2" in ids
        assert "s3" in ids

    def test_empty_document_returns_empty(
        self,
        classifier: ProceduralDocumentClassifier,
    ):
        source = make_source(sections=[])
        sections, origins = classifier.classify(source)
        assert sections == []
        assert origins == {}

    def test_section_key_falls_back_to_order(
        self,
        classifier: ProceduralDocumentClassifier,
    ):
        source = make_source(sections=[
            make_section(
                section_type="procedure",
                section_order=7,
                id=None,
            ),
        ])
        _, origins = classifier.classify(source)
        assert "section_7" in origins
