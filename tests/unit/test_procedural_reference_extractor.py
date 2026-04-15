"""Unit tests for ``ProceduralReferenceExtractor``.

Three-pass: regex extraction + asset cataloging + LLM + dedup.
"""

from __future__ import annotations

import pytest

from fault_mapper.domain.enums import MappingStrategy
from fault_mapper.domain.procedural_value_objects import (
    ReferenceInterpretation,
)

from fault_mapper.application.procedural_reference_extractor import (
    ProceduralReferenceExtractor,
)

from tests.conftest import (
    FakeProceduralLlmInterpreter,
    FakeProceduralRulesEngine,
    make_image,
    make_section,
    make_table,
)


@pytest.fixture
def extractor(
    fake_procedural_rules: FakeProceduralRulesEngine,
    fake_procedural_llm: FakeProceduralLlmInterpreter,
) -> ProceduralReferenceExtractor:
    return ProceduralReferenceExtractor(
        rules=fake_procedural_rules,
        llm=fake_procedural_llm,
    )


class TestRegexExtraction:
    def test_extracts_dm_ref(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.reference_results = []
        section = make_section(
            section_text="Refer to DMC-29-10-00 for details.",
            id="s1",
        )
        refs, _, _, origins = extractor.extract([section], {})

        dm_refs = [r for r in refs if r.ref_type == "dm_ref"]
        assert len(dm_refs) >= 1
        assert dm_refs[0].target_dm_code is not None

    def test_extracts_figure_ref(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.reference_results = []
        section = make_section(
            section_text="See Figure 3 for assembly diagram.",
            id="s1",
        )
        refs, _, _, origins = extractor.extract([section], {})

        fig_refs = [r for r in refs if r.ref_type == "figure_ref"]
        assert len(fig_refs) >= 1
        assert fig_refs[0].target_id == "fig-3"

    def test_extracts_table_ref(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.reference_results = []
        section = make_section(
            section_text="See Table 5 for torque values.",
            id="s1",
        )
        refs, _, _, origins = extractor.extract([section], {})

        tbl_refs = [r for r in refs if r.ref_type == "table_ref"]
        assert len(tbl_refs) >= 1

    def test_regex_origins_are_rule(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.reference_results = []
        section = make_section(
            section_text="Refer to DM 123-456.",
            id="s1",
        )
        _, _, _, origins = extractor.extract([section], {})

        rule_origins = [
            o for o in origins.values()
            if o.strategy == MappingStrategy.RULE
        ]
        assert len(rule_origins) >= 1


class TestAssetCataloging:
    def test_catalogs_images_as_figures(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.reference_results = []
        image = make_image(caption="Exploded view", id="img-1")
        section = make_section(
            section_text="No references in text.",
            images=[image],
            id="s1",
        )
        _, figures, _, origins = extractor.extract([section], {})

        assert len(figures) >= 1
        assert figures[0].caption == "Exploded view"

    def test_catalogs_tables(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.reference_results = []
        table = make_table(caption="Torque Values", id="tbl-1")
        section = make_section(
            section_text="No references in text.",
            tables=[table],
            id="s1",
        )
        _, _, table_refs, origins = extractor.extract([section], {})

        assert len(table_refs) >= 1
        assert table_refs[0].caption == "Torque Values"

    def test_asset_origins_are_direct(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.reference_results = []
        image = make_image(id="img-1")
        section = make_section(
            section_text="Plain text.",
            images=[image],
            id="s1",
        )
        _, _, _, origins = extractor.extract([section], {})

        direct_origins = [
            o for o in origins.values()
            if o.strategy == MappingStrategy.DIRECT
        ]
        assert len(direct_origins) >= 1


class TestLlmExtraction:
    def test_llm_refs_above_threshold(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_llm.reference_results = [
            ReferenceInterpretation(
                ref_type="external",
                target_text="ATA Chapter 32",
                label="ATA 32",
                confidence=0.90,
            ),
        ]
        section = make_section(section_text="See ATA 32.", id="s1")
        refs, _, _, origins = extractor.extract([section], {})

        ext_refs = [r for r in refs if r.ref_type == "external"]
        assert len(ext_refs) >= 1

    def test_llm_refs_below_threshold_filtered(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_rules: FakeProceduralRulesEngine,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        fake_procedural_rules.threshold_value = 0.80
        fake_procedural_llm.reference_results = [
            ReferenceInterpretation(
                ref_type="dm_ref",
                target_text="maybe DMC",
                confidence=0.50,
            ),
        ]
        section = make_section(
            section_text="No regex matches here.",
            id="s1",
        )
        refs, _, _, _ = extractor.extract([section], {})
        llm_dm_refs = [r for r in refs if r.ref_type == "dm_ref"]
        assert len(llm_dm_refs) == 0


class TestDeduplication:
    def test_duplicate_refs_removed(
        self,
        extractor: ProceduralReferenceExtractor,
        fake_procedural_llm: FakeProceduralLlmInterpreter,
    ):
        # Regex and LLM both find same DM ref
        fake_procedural_llm.reference_results = [
            ReferenceInterpretation(
                ref_type="dm_ref",
                target_text="DMC-29-10-00",
                target_dm_code="29-10-00",
                confidence=0.90,
            ),
        ]
        section = make_section(
            section_text="See DM 29-10-00 for the procedure.",
            id="s1",
        )
        refs, _, _, _ = extractor.extract([section], {})

        dm_refs = [r for r in refs if r.ref_type == "dm_ref"]
        # Dedup should have removed duplicates
        dm_codes = [r.target_dm_code for r in dm_refs]
        assert len(dm_codes) == len(set(dm_codes))


class TestEmptyInput:
    def test_no_sections_returns_empty(
        self,
        extractor: ProceduralReferenceExtractor,
    ):
        refs, figs, tbls, origins = extractor.extract([], {})
        assert refs == []
        assert figs == []
        assert tbls == []
        assert origins == {}
