"""Unit tests for ``FaultTableClassifier``.

Two-pass: RULE (header pattern) → LLM fallback → UNKNOWN default.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import TableType
from fault_mapper.domain.value_objects import TableClassification

from fault_mapper.application.fault_table_classifier import FaultTableClassifier

from tests.conftest import (
    FakeLlmInterpreter,
    FakeRulesEngine,
    make_table,
)


@pytest.fixture
def classifier(
    fake_rules: FakeRulesEngine,
    fake_llm: FakeLlmInterpreter,
) -> FaultTableClassifier:
    return FaultTableClassifier(rules=fake_rules, llm=fake_llm)


class TestRulePass:
    def test_headers_match_rule_classification(
        self,
        classifier: FaultTableClassifier,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.table_by_headers_value = TableType.LRU_LIST
        table = make_table(headers=["Part Number", "LRU Name", "Qty"])

        result = classifier.classify(table)
        assert result.role == TableType.LRU_LIST
        assert result.confidence == 1.0
        assert "Rule-based" in result.reasoning
        # LLM not called
        assert len(fake_llm.calls["classify_table"]) == 0

    def test_no_headers_falls_to_llm(
        self,
        classifier: FaultTableClassifier,
        fake_llm: FakeLlmInterpreter,
    ):
        table = make_table(headers=[])
        result = classifier.classify(table)
        assert len(fake_llm.calls["classify_table"]) == 1

    def test_headers_inconclusive_falls_to_llm(
        self,
        classifier: FaultTableClassifier,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.table_by_headers_value = None  # inconclusive
        table = make_table(headers=["A", "B"])
        result = classifier.classify(table)
        assert len(fake_llm.calls["classify_table"]) == 1


class TestLlmFallback:
    def test_llm_above_threshold_accepted(
        self,
        classifier: FaultTableClassifier,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.table_by_headers_value = None
        fake_rules.threshold_value = 0.80
        fake_llm.table_classification_result = TableClassification(
            role=TableType.SRU_LIST,
            confidence=0.90,
            reasoning="LLM classified as SRU",
        )
        table = make_table(headers=["X"])
        result = classifier.classify(table)
        assert result.role == TableType.SRU_LIST
        assert result.confidence == 0.90

    def test_llm_below_threshold_returns_unknown(
        self,
        classifier: FaultTableClassifier,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.table_by_headers_value = None
        fake_rules.threshold_value = 0.80
        fake_llm.table_classification_result = TableClassification(
            role=TableType.SPARES,
            confidence=0.50,
            reasoning="uncertain",
        )
        table = make_table(headers=["X"])
        result = classifier.classify(table)
        assert result.role == TableType.UNKNOWN
        assert result.confidence == 0.50
        assert "Below threshold" in result.reasoning


class TestClassifyAll:
    def test_classifies_multiple_tables(
        self,
        classifier: FaultTableClassifier,
        fake_rules: FakeRulesEngine,
    ):
        fake_rules.table_by_headers_value = TableType.GENERAL
        tables = [
            make_table(id="t1", headers=["A"]),
            make_table(id="t2", headers=["B"]),
            make_table(id=None, headers=["C"]),  # no id → table_2
        ]
        result = classifier.classify_all(tables)
        assert "t1" in result
        assert "t2" in result
        assert "table_2" in result
        assert len(result) == 3

    def test_empty_list(self, classifier: FaultTableClassifier):
        assert classifier.classify_all([]) == {}
