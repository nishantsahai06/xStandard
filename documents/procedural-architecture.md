# Procedural Data Module — Architecture Skeleton (Chunk 1)

> **Status**: Skeleton only — no business logic, no mapping logic, no LLM prompts, no validation logic, no persistence logic.
> **Test baseline**: 563 passed, 65 skipped (zero regressions from fault module pipeline).

---

## 1. Architecture Summary

The procedural data module mapping branch extends the existing JSON-native CSDB mapping platform to handle **S1000D procedural data modules** (maintenance procedures, installation/removal tasks, inspection steps, servicing instructions).

It follows the **identical hexagonal architecture** as the fault module pipeline:

```
┌──────────────────────────────────────────────────────────────────────┐
│                        DOMAIN LAYER (pure)                          │
│                                                                      │
│  procedural_enums.py    ← ProceduralSectionType, StepType,          │
│                           ActionType, ProceduralModuleType           │
│  procedural_value_objects.py ← LLM interpretation VOs,              │
│                                 ProceduralSectionLineage             │
│  procedural_models.py   ← S1000DProceduralDataModule (root aggr.)   │
│                           ProceduralStep, ProceduralSection,         │
│                           ProceduralContent, ProceduralHeader, etc.  │
│  procedural_ports.py    ← ProceduralLlmInterpreterPort,             │
│                           ProceduralRulesEnginePort,                 │
│                           ProceduralReviewPolicyPort                 │
├──────────────────────────────────────────────────────────────────────┤
│                     APPLICATION LAYER (orchestration)                │
│                                                                      │
│  procedural_mapping_use_case.py  ← 7-step pipeline orchestrator     │
│  procedural_document_classifier.py ← section filtering              │
│  procedural_header_builder.py      ← DM header construction         │
│  procedural_section_organizer.py   ← section classification/ordering│
│  procedural_step_extractor.py      ← step extraction + nesting      │
│  procedural_requirement_extractor.py ← prelim requirements          │
│  procedural_reference_extractor.py   ← cross-reference extraction   │
│  procedural_module_assembler.py      ← root aggregate assembly      │
├──────────────────────────────────────────────────────────────────────┤
│                    INFRASTRUCTURE LAYER (wiring)                     │
│                                                                      │
│  procedural_config.py   ← ProceduralAppConfig (DM defaults,         │
│                           thresholds, keywords, title rules)         │
│  procedural_factory.py  ← ProceduralMapperFactory (composition root)│
└──────────────────────────────────────────────────────────────────────┘
```

**Key principle**: This is NOT a separate product. It is a new module-type branch within the same CSDB mapping platform. It reuses the shared source models (`DocumentPipelineOutput`), shared value objects (`DmCode`, `MappingTrace`, `FieldOrigin`, etc.), shared enums (`MappingStrategy`, `ValidationStatus`, `ReviewStatus`, etc.), and shared infrastructure ports (`FaultModuleRepositoryPort`, `MetricsSinkPort`, `AuditRepositoryPort`, etc.).

---

## 2. Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Parallel files, not sub-packages** | New procedural files live alongside fault files in `domain/`, `application/`, `infrastructure/` — same flat structure, `procedural_` prefix for namespace clarity. Avoids refactoring existing imports. |
| D2 | **Reuse all source-side models** | `DocumentPipelineOutput`, `Section`, `Chunk`, `TableAsset`, `ImageAsset`, `SchematicsItem`, `Metadata` are pipeline-generic. Zero duplication. |
| D3 | **Reuse shared S1000D building blocks** | `Ref`, `NoteLike`, `TypedText`, `FigureRef`, `CommonInfo`, `PreliminaryRequirements`, `CloseRequirements`, `Provenance`, `Classification`, `XmlMeta` are S1000D-generic, not fault-specific. Imported from `models.py`. |
| D4 | **Reuse all shared value objects** | `DmCode`, `Language`, `IssueInfo`, `IssueDate`, `DmTitle`, `FieldOrigin`, `MappingTrace`, `ValidationIssue`, `ModuleValidationResult`, `ReviewDecision`, `PersistenceEnvelope`, `PersistenceResult`, `AuditEntry`, `BatchItemResult`, `BatchReport` — all reused. |
| D5 | **Reuse all shared enums** | `MappingStrategy`, `ValidationStatus`, `ReviewStatus`, `ValidationOutcome`, `ValidationSeverity`, `ClassificationMethod`, `NoteLikeKind`, `AuditEventType`, `ReconciliationOutcome` — all reused. Only procedural-specific enums are new. |
| D6 | **Parallel `ProceduralHeader` type** | Structurally identical to `FaultHeader` but named for type clarity. A future chunk may extract a shared `DataModuleHeader` base. |
| D7 | **New procedural ports** | `ProceduralLlmInterpreterPort` and `ProceduralRulesEnginePort` are narrow, cohesive ports specific to procedural interpretation. Shared ports (persistence, audit, metrics, handoff) are reused unchanged. |
| D8 | **7-step use case pipeline** | Classify → Header → Organize → Extract Steps → Extract Requirements → Extract References → Assemble. Mirrors the fault pipeline's 6-step pattern with procedural-specific decomposition. |
| D9 | **All service methods raise `NotImplementedError`** | Skeleton only — every public method has a complete docstring, type hints, and TODO markers for Chunk 2+ implementation. |
| D10 | **Reuse shared infrastructure ports for persistence** | `FaultModuleRepositoryPort` (misnamed — it's generic) and `AuditRepositoryPort` are reused. A future chunk may rename to `ModuleRepositoryPort`. |
| D11 | **Separate config aggregate** | `ProceduralAppConfig` reuses `LlmConfig` and `MongoConfig` but has its own `ProceduralMappingConfig` with procedural-specific DM-code defaults, thresholds, and keywords. |

---

## 3. Package Structure

```
fault_mapper/
├── domain/
│   ├── __init__.py
│   ├── enums.py                          # Shared enums (unchanged)
│   ├── models.py                         # Source models + fault target models (unchanged)
│   ├── ports.py                          # Shared ports (unchanged)
│   ├── value_objects.py                  # Shared VOs (unchanged)
│   ├── procedural_enums.py              # NEW — ProceduralSectionType, StepType, ActionType, ProceduralModuleType
│   ├── procedural_value_objects.py      # NEW — LLM interpretation VOs + ProceduralSectionLineage
│   ├── procedural_models.py             # NEW — S1000DProceduralDataModule + 7 sub-models
│   └── procedural_ports.py             # NEW — ProceduralLlmInterpreterPort, ProceduralRulesEnginePort, ProceduralReviewPolicyPort
├── application/
│   ├── __init__.py
│   ├── fault_mapping_use_case.py        # Existing fault orchestrator (unchanged)
│   ├── fault_*.py                       # Existing fault services (unchanged)
│   ├── procedural_mapping_use_case.py   # NEW — 7-step procedural orchestrator
│   ├── procedural_document_classifier.py # NEW — section filtering
│   ├── procedural_header_builder.py     # NEW — DM header construction
│   ├── procedural_section_organizer.py  # NEW — section classification + ordering
│   ├── procedural_step_extractor.py     # NEW — step extraction + sub-step nesting
│   ├── procedural_requirement_extractor.py # NEW — preliminary requirements
│   ├── procedural_reference_extractor.py # NEW — cross-reference extraction
│   └── procedural_module_assembler.py   # NEW — root aggregate assembly
├── infrastructure/
│   ├── __init__.py
│   ├── config.py                        # Existing fault config (unchanged)
│   ├── factory.py                       # Existing fault factory (unchanged)
│   ├── procedural_config.py            # NEW — ProceduralAppConfig + sub-configs
│   └── procedural_factory.py           # NEW — ProceduralMapperFactory
└── adapters/                            # Unchanged — concrete adapters added in Chunk 2+
```

**Total new files: 14**  |  **Modified existing files: 0**

---

## 4. File Responsibility Map

### Domain Layer

| File | Types | Responsibility |
|------|-------|---------------|
| `procedural_enums.py` | `ProceduralSectionType` (10 values), `StepType` (6), `ActionType` (13), `ProceduralModuleType` (2) | Procedural-specific enum values for section classification, step typing, action verbs, and module flavour. All `str`-backed for JSON serialisation. |
| `procedural_value_objects.py` | `SectionClassificationInterpretation`, `StepInterpretation`, `RequirementInterpretation`, `ReferenceInterpretation`, `ProceduralRelevanceAssessment`, `ProceduralSectionLineage` | Frozen dataclasses for LLM interpretation results (never trusted directly) and per-section lineage tracking. |
| `procedural_models.py` | `ProceduralTableRef`, `ProceduralStep`, `ProceduralSection`, `MainProcedure`, `ProceduralContent`, `ProceduralHeader`, `ProceduralValidationResults`, `S1000DProceduralDataModule` | Canonical target-side models. `ProceduralStep` and `ProceduralSection` are recursive (sub-steps, sub-sections). `S1000DProceduralDataModule` is the root aggregate with trust axes. |
| `procedural_ports.py` | `ProceduralLlmInterpreterPort` (6 methods), `ProceduralRulesEnginePort` (12 methods), `ProceduralReviewPolicyPort` (1 method) | `@runtime_checkable` Protocol interfaces. LLM port handles relevance, classification, step/requirement/reference extraction. Rules port handles DM-code, keywords, section heuristics, step normalisation, thresholds. |

### Application Layer

| File | Class | Responsibility |
|------|-------|---------------|
| `procedural_document_classifier.py` | `ProceduralDocumentClassifier` | Two-pass (rules → LLM) filtering of source sections for procedural relevance. Returns `(sections, origins)`. |
| `procedural_header_builder.py` | `ProceduralHeaderBuilder` | Pure-rules DM header construction (dm_code, language, issue_info, issue_date, dm_title). No LLM. |
| `procedural_section_organizer.py` | `ProceduralSectionOrganizer` | Two-pass (rules → LLM) classification of sections into `ProceduralSectionType`. Determines ordering and nesting. |
| `procedural_step_extractor.py` | `ProceduralStepExtractor` | LLM-assisted step extraction from section text. Detects nesting, classifies step/action types, extracts step-level warnings/cautions/notes. |
| `procedural_requirement_extractor.py` | `ProceduralRequirementExtractor` | Two-pass (table headers → LLM) extraction of preliminary requirements (personnel, equipment, supplies, spares, safety). |
| `procedural_reference_extractor.py` | `ProceduralReferenceExtractor` | Two-pass (regex → LLM) extraction of DM refs, figure refs, table refs, external refs. |
| `procedural_module_assembler.py` | `ProceduralModuleAssembler` | Deterministic assembly of `S1000DProceduralDataModule` from all upstream outputs. Builds `Provenance`, `MappingTrace`, sets trust axes. |
| `procedural_mapping_use_case.py` | `ProceduralMappingUseCase` | 7-step pipeline orchestrator. Single entry-point: `execute(source, module_type) → S1000DProceduralDataModule`. |

### Infrastructure Layer

| File | Types | Responsibility |
|------|-------|---------------|
| `procedural_config.py` | `ProceduralDmCodeDefaults`, `ProceduralThresholdConfig`, `ProceduralKeywordConfig`, `ProceduralTitleConfig`, `ProceduralMappingConfig`, `ProceduralAppConfig` | All frozen dataclasses. DM-code info codes default to `"040"`/`"041"`. Reuses `LlmConfig` and `MongoConfig`. |
| `procedural_factory.py` | `ProceduralMapperFactory`, `build_procedural_mapper()` | Composition root. Wires ports → adapters → services → use case. Currently raises `NotImplementedError` until Chunk 2+ adapters exist. |

---

## 5. Minimal Code Scaffolding

All 14 files are created with:

- ✅ Module-level docstrings explaining purpose, analogies to fault counterparts, and responsibility boundaries
- ✅ All imports resolved (verified by import test)
- ✅ Full type hints on all methods (parameters + return types)
- ✅ Comprehensive docstrings on all public methods with Parameters/Returns/TODO sections
- ✅ `NotImplementedError` in every method body with descriptive message referencing "Chunk 2+"
- ✅ `TODO: Chunk 2+` markers on every deferred implementation
- ✅ Constructor injection of domain ports (same pattern as fault services)
- ✅ Domain convenience properties on root aggregate (`is_procedural`, `is_trusted`, `total_steps`, `total_sections`)
- ✅ Recursive data structures: `ProceduralStep.sub_steps`, `ProceduralSection.sub_sections`

**Types inventory**:
| Layer | Dataclasses | Enums | Protocols | Service classes | Total |
|-------|------------|-------|-----------|----------------|-------|
| Domain | 14 | 4 (31 values) | 3 | — | 21 |
| Application | — | — | — | 8 | 8 |
| Infrastructure | 6 | — | — | 1 | 7 |
| **Total** | **20** | **4** | **3** | **9** | **36** |

---

## 6. Dependency Flow

```
ProceduralMappingUseCase
├── ProceduralDocumentClassifier
│   ├── ProceduralRulesEnginePort      ← deterministic rules
│   └── ProceduralLlmInterpreterPort   ← LLM fallback
├── ProceduralHeaderBuilder
│   └── ProceduralRulesEnginePort      ← DM-code, title, dates
├── ProceduralSectionOrganizer
│   ├── ProceduralRulesEnginePort      ← structural classification
│   └── ProceduralLlmInterpreterPort   ← LLM fallback
├── ProceduralStepExtractor
│   ├── ProceduralRulesEnginePort      ← step normalisation, thresholds
│   └── ProceduralLlmInterpreterPort   ← step extraction
├── ProceduralRequirementExtractor
│   ├── ProceduralRulesEnginePort      ← table matching, thresholds
│   └── ProceduralLlmInterpreterPort   ← requirement extraction
├── ProceduralReferenceExtractor
│   ├── ProceduralRulesEnginePort      ← regex patterns, thresholds
│   └── ProceduralLlmInterpreterPort   ← reference extraction
└── ProceduralModuleAssembler
    ├── ProceduralRulesEnginePort      ← record ID, mapping version
    └── ProceduralReviewPolicyPort     ← optional review policy
```

**Cross-module reuse** (no new dependencies — all pre-existing):
- `DocumentPipelineOutput` ← shared source model
- `Ref`, `NoteLike`, `PreliminaryRequirements`, `Provenance`, etc. ← shared target building blocks
- `FieldOrigin`, `MappingTrace` ← shared traceability VOs
- `FaultModuleRepositoryPort`, `AuditRepositoryPort`, `MetricsSinkPort` ← shared infra ports
- `LlmConfig`, `MongoConfig` ← shared config types

---

## 7. Guardrails

### What Chunk 1 delivers
- [x] 14 new Python files across domain / application / infrastructure
- [x] 36 new types (20 dataclasses, 4 enums, 3 protocols, 9 service classes)
- [x] All imports verified — every module resolves cleanly
- [x] Zero modifications to existing fault module files
- [x] Full test suite passes: **563 passed, 65 skipped** (identical to pre-chunk baseline)
- [x] Complete docstrings with type hints, TODO markers, and responsibility boundaries
- [x] Clear `NotImplementedError` barriers on every deferred method

### What Chunk 1 does NOT deliver
- ❌ No business logic (all methods raise `NotImplementedError`)
- ❌ No mapping logic
- ❌ No LLM prompts or prompt templates
- ❌ No validation logic (structural or business-rule)
- ❌ No persistence logic
- ❌ No concrete adapter implementations
- ❌ No API endpoints or CLI commands
- ❌ No tests for procedural modules (deferred to implementation chunks)

### Future refactoring opportunities (documented, not acted on)
1. **Shared `DataModuleHeader`** — extract from `FaultHeader` + `ProceduralHeader` when both are stable
2. **Rename `FaultModuleRepositoryPort`** → `ModuleRepositoryPort` (generic for any module type)
3. **Unified `PlatformConfig`** — single root config containing both fault and procedural `MappingConfig`
4. **Shared rules engine methods** — `generate_record_id()`, `resolve_issue_info()`, `resolve_issue_date()`, `default_language()` can be extracted into a `SharedRulesEnginePort`
5. **Module-type router** — a top-level classifier that routes `DocumentPipelineOutput` to the correct pipeline (fault vs procedural vs descriptive vs …)

### Chunk 2+ roadmap
| Chunk | Scope |
|-------|-------|
| 2 | Concrete `ProceduralRulesAdapter` + `ProceduralLlmInterpreterAdapter` |
| 3 | `ProceduralDocumentClassifier` + `ProceduralHeaderBuilder` implementation |
| 4 | `ProceduralSectionOrganizer` + `ProceduralStepExtractor` implementation |
| 5 | `ProceduralRequirementExtractor` + `ProceduralReferenceExtractor` implementation |
| 6 | `ProceduralModuleAssembler` + `ProceduralMappingUseCase` end-to-end |
| 7 | Validation, persistence, review, API/CLI integration |
| 8 | Batch processing, async support, observability |
