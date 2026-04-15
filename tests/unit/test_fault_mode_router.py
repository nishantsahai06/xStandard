"""Unit tests for ``FaultModeRouter``.

Two-pass service: RULE (structural) → LLM fallback → default.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import FaultMode, MappingStrategy
from fault_mapper.domain.value_objects import FaultModeInterpretation

from fault_mapper.application.fault_mode_router import FaultModeRouter

from tests.conftest import (
    FakeLlmInterpreter,
    FakeRulesEngine,
    make_section,
)


@pytest.fixture
def router(
    fake_rules: FakeRulesEngine,
    fake_llm: FakeLlmInterpreter,
) -> FaultModeRouter:
    return FaultModeRouter(rules=fake_rules, llm=fake_llm)


class TestRulePass:
    def test_rule_resolves_reporting(
        self,
        router: FaultModeRouter,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.mode_by_structure_value = FaultMode.FAULT_REPORTING
        sections = [make_section()]
        mode, origin = router.resolve(sections)

        assert mode is FaultMode.FAULT_REPORTING
        assert origin.strategy == MappingStrategy.RULE
        assert origin.confidence == 1.0
        # LLM should NOT have been called
        assert len(fake_llm.calls["interpret_fault_mode"]) == 0

    def test_rule_resolves_isolation(
        self,
        router: FaultModeRouter,
        fake_rules: FakeRulesEngine,
    ):
        fake_rules.mode_by_structure_value = FaultMode.FAULT_ISOLATION
        mode, origin = router.resolve([make_section()])
        assert mode is FaultMode.FAULT_ISOLATION


class TestLlmFallback:
    def test_llm_above_threshold(
        self,
        router: FaultModeRouter,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.mode_by_structure_value = None  # inconclusive
        fake_rules.threshold_value = 0.80
        fake_llm.mode_result = FaultModeInterpretation(
            mode=FaultMode.FAULT_ISOLATION,
            confidence=0.92,
            reasoning="clear isolation steps",
        )

        mode, origin = router.resolve([make_section()])
        assert mode is FaultMode.FAULT_ISOLATION
        assert origin.strategy == MappingStrategy.LLM
        assert origin.confidence == 0.92

    def test_llm_below_threshold_defaults_to_reporting(
        self,
        router: FaultModeRouter,
        fake_rules: FakeRulesEngine,
        fake_llm: FakeLlmInterpreter,
    ):
        fake_rules.mode_by_structure_value = None
        fake_rules.threshold_value = 0.80
        fake_llm.mode_result = FaultModeInterpretation(
            mode=FaultMode.FAULT_ISOLATION,
            confidence=0.50,  # below threshold
            reasoning="uncertain",
        )

        mode, origin = router.resolve([make_section()])
        assert mode is FaultMode.FAULT_REPORTING  # conservative default
        assert origin.strategy == MappingStrategy.LLM
        assert origin.confidence == 0.50  # actual low confidence preserved


class TestEdgeCases:
    def test_empty_sections_raises(self, router: FaultModeRouter):
        with pytest.raises(ValueError, match="empty section list"):
            router.resolve([])

    def test_delegates_to_rules_first(
        self,
        router: FaultModeRouter,
        fake_rules: FakeRulesEngine,
    ):
        fake_rules.mode_by_structure_value = FaultMode.FAULT_REPORTING
        router.resolve([make_section()])
        assert len(fake_rules.calls["assess_mode_by_structure"]) == 1
