# xStandard — S1000D Fault Mapper: Progress Report

**Date:** 15 April 2026  
**Repository:** https://github.com/nishantsahai06/xStandard  
**Runtime:** Python 3.13.3 · macOS ARM · pytest 9.0.3

---

## Executive Summary

A hexagonal-architecture S1000D data-module mapper that transforms unstructured
maintenance documents into structured S1000D XML-ready data modules. The project
currently covers **two module families** — Fault and Procedural — with a shared
domain core.

| Metric | Value |
|---|---|
| Python source files | 71 |
| Test files | 57 |
| Total Python LOC | ~31,000 |
| Tests collected | 699 |
| **Tests passing** | **634** |
| Tests skipped | 65 (integration, require MongoDB / network) |
| Tests failing | **0** |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Primary Adapters   (API · CLI)                     │
├─────────────────────────────────────────────────────┤
│  Application Layer  (Use Cases · Services)          │
│    ├── Fault:  12 services                          │
│    └── Procedural:  8 services                      │
├─────────────────────────────────────────────────────┤
│  Domain Layer  (Models · Value Objects · Ports)     │
│    ├── Shared: 42 models, 22 VOs, 8 enums          │
│    ├── Fault:  ports (Rules + LLM)                  │
│    └── Procedural: ports (Rules 12m + LLM 6m)      │
├─────────────────────────────────────────────────────┤
│  Secondary Adapters (Rules · LLM · Repository ·     │
│    Serializer · Validator · Review Gate)             │
├─────────────────────────────────────────────────────┤
│  Infrastructure  (Config · Factory · Wiring)        │
└─────────────────────────────────────────────────────┘
```

**Key principles:** Constructor injection · Ports & adapters · Frozen value
objects · Copy-on-write immutability · Fakes over mocks · Network-free tests

---

## Chunk Progress

### ✅ Chunk 1 — Architecture Skeleton

Created the full procedural module scaffolding (14 files):

| Layer | Files | Contents |
|---|---|---|
| Domain | 4 | `procedural_enums.py` (3 enums, 25 members), `procedural_value_objects.py` (6 frozen VOs), `procedural_models.py` (root aggregate + 9 sub-models), `procedural_ports.py` (2 ports: Rules 12 methods, LLM 6 methods) |
| Application | 8 | `procedural_document_classifier.py`, `procedural_header_builder.py`, `procedural_section_organizer.py`, `procedural_step_extractor.py`, `procedural_requirement_extractor.py`, `procedural_reference_extractor.py`, `procedural_module_assembler.py`, `procedural_mapping_use_case.py` |
| Infrastructure | 2 | `procedural_config.py` (3 frozen config dataclasses), `procedural_factory.py` (composition root) |

### ✅ Chunk 2 — Real Domain + Application Logic

Rewrote all 8 application services and 3 domain files from stubs to production
logic:

- **Document Classifier:** Two-pass RULE+LLM filter with keyword sets and semantic fallback
- **Header Builder:** 5 deterministic rules calls, zero LLM dependency
- **Section Organizer:** RULE structural classification + LLM fallback + sort-by-order
- **Step Extractor:** LLM extraction → confidence gate → sub-step wiring → notice detection
- **Requirement Extractor:** Table scan (DIRECT) + LLM prose (confidence-gated) + dedup
- **Reference Extractor:** Regex (DMC/FIG/TBL) + asset catalog + LLM + dedup
- **Module Assembler:** Deterministic assembly with provenance, trace, lineage, classification
- **Mapping Use Case:** 7-step pipeline with `dataclasses.replace()` copy-on-write

### ✅ Chunk 3 — Adapters, Fakes, Tests, Factory Wiring

Made the procedural branch executable in isolation:

#### Adapters (2 new files)

| Adapter | Methods | Strategy |
|---|---|---|
| `ProceduralRulesAdapter` | 12 | Config-driven deterministic: header/DM-code (7), heuristic classification (3), step normalisation (1), threshold lookup (1) |
| `ProceduralLlmInterpreterAdapter` | 6 | Prompt → LLM → JSON parse → typed VOs, fail-safe defaults on error |

#### Test Doubles (2 new files)

| Fake | Methods | Features |
|---|---|---|
| `FakeProceduralRulesEngine` | 12 | Canned returns via public attributes, `calls` dict for tracking |
| `FakeProceduralLlmInterpreter` | 6 | Canned VOs (`StepInterpretation`, `RequirementInterpretation`, `ReferenceInterpretation`), call tracking |

#### Unit Tests (8 new files, 71 tests)

| Test File | Tests | Key Scenarios |
|---|---|---|
| `test_procedural_document_classifier` | 10 | RULE type/keyword match, LLM above/below threshold, mixed sections, empty input |
| `test_procedural_header_builder` | 5 | All fields, all-RULE origins, delegation, module_type passthrough |
| `test_procedural_section_organizer` | 7 | Rule classification, LLM fallback, ordering, empty input |
| `test_procedural_step_extractor` | 9 | LLM extraction, confidence filter, sub-steps, notices, chunk IDs |
| `test_procedural_requirement_extractor` | 8 | Equipment table, non-req skip, empty rows, LLM prose, dedup |
| `test_procedural_reference_extractor` | 11 | DMC/FIG/TBL regex, asset catalog, LLM, dedup, empty input |
| `test_procedural_module_assembler` | 13 | Completeness, provenance, trace, lineage, validation, review, classification |
| `test_procedural_mapping_use_case` | 8 | End-to-end, error handling, copy-on-write, multi-section, trace integrity |

#### Infrastructure Changes

- **`procedural_config.py`** — Expanded `ProceduralDmCodeDefaults` (10 DM-code segments) and `ProceduralMappingConfig` (language/country/issue defaults)
- **`procedural_factory.py`** — Rewired from `NotImplementedError` to real adapter construction
- **`conftest.py`** — Added `fake_procedural_rules` and `fake_procedural_llm` fixtures

---

## Pre-existing Fault Module (complete before these sessions)

The fault module pipeline was already fully built and tested:

- 12 application services (selector, router, isolation mapper, reporting mapper, header builder, table classifier, schematic correlator, assembler, validator, persistence, review, reconciliation)
- Adapters: RulesAdapter (14 methods), LlmInterpreterAdapter (7 methods), MongoDB repository, serializer, validators, review gate
- 7 fake test doubles
- Full async variants for batch processing, persistence, reconciliation, review
- API (FastAPI) and CLI entry points
- 563 passing tests, 65 skipped (integration)

---

## File Inventory

### Source (`fault_mapper/`)

```
fault_mapper/
├── __init__.py
├── domain/
│   ├── enums.py                     # Shared enums (8)
│   ├── models.py                    # Shared models (42 dataclasses)
│   ├── value_objects.py             # Shared VOs (22 frozen dataclasses)
│   ├── ports.py                     # Fault domain ports
│   ├── procedural_enums.py          # Procedural enums (3)
│   ├── procedural_models.py         # Procedural aggregate + sub-models
│   ├── procedural_value_objects.py  # Procedural VOs (6 frozen)
│   └── procedural_ports.py          # Procedural ports (Rules 12m, LLM 6m)
├── application/
│   ├── _shared_helpers.py
│   ├── fault_*.py                   # 12 fault application services
│   ├── procedural_*.py              # 8 procedural application services
│   └── async_*.py                   # 4 async service variants
├── adapters/
│   ├── primary/api/                 # FastAPI routes, DTOs, dependencies
│   ├── primary/cli/                 # CLI entry point
│   └── secondary/
│       ├── rules_adapter.py         # Fault rules (14 methods)
│       ├── llm_interpreter_adapter.py
│       ├── procedural_rules_adapter.py    # NEW — Chunk 3
│       ├── procedural_llm_interpreter_adapter.py  # NEW — Chunk 3
│       ├── mongodb_repository.py
│       ├── module_serializer.py
│       ├── business_rule_validator.py
│       ├── schema_validator.py
│       ├── structural_validator.py
│       ├── review_gate.py
│       └── in_memory_*.py / async_*.py
├── infrastructure/
│   ├── config.py                    # Fault config
│   ├── factory.py                   # Fault factory
│   ├── procedural_config.py         # Procedural config — expanded Chunk 3
│   └── procedural_factory.py        # Procedural factory — wired Chunk 3
└── schemas/
    └── fault_data_module.schema.json
```

### Tests (`tests/`)

```
tests/
├── conftest.py                      # Shared factories + fixtures (expanded Chunk 3)
├── fakes/
│   ├── fake_rules_engine.py
│   ├── fake_llm_interpreter.py
│   ├── fake_fault_module_repository.py
│   ├── fake_audit_repository.py
│   ├── fake_mapping_review_policy.py
│   ├── fake_procedural_rules_engine.py        # NEW — Chunk 3
│   ├── fake_procedural_llm_interpreter.py     # NEW — Chunk 3
│   └── async_fake_*.py
├── unit/
│   ├── test_fault_*.py              # 20 fault unit test files
│   ├── test_procedural_*.py         # 8 procedural unit test files — NEW Chunk 3
│   └── test_shared_helpers.py
├── integration/
│   ├── test_end_to_end_workflow.py
│   ├── test_mongodb_repository_integration.py
│   └── test_persistence_workflow_integration.py
├── api/test_api.py
└── cli/test_cli.py
```

---

## Remaining Work (Future Chunks)

| Chunk | Scope | Status |
|---|---|---|
| 4 | Procedural integration tests with real LLM, JSON schema for procedural module | Not started |
| 5 | Persistence layer (MongoDB adapter for procedural modules) | Not started |
| 6 | Review workflow + validation pipeline for procedural modules | Not started |
| 7 | CLI/API entry points for procedural pipeline | Not started |
| 8 | Cross-module orchestration (fault + procedural in single run) | Not started |

---

## Known Risks

1. **LLM adapter JSON parsing** — Only tested via fakes; malformed response handling needs integration tests
2. **No procedural persistence** — Deliberately deferred; MongoDB adapter not yet wired
3. **Section-type keyword heuristics** — 8 types covered; real-world edge cases may need tuning
4. **Review policy** — Assembler accepts optional callable but no concrete policy exists yet
5. **65 skipped tests** — All integration tests requiring MongoDB or network; pass when infra available
