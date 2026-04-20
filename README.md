# fault-mapper

> **Hybrid mapper that transforms `DocumentPipelineOutput` JSON into validated, canonical [S1000D](https://s1000d.org/) Data Modules — Fault Data Modules and Procedural Data Modules.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#requirements)
[![Tests](https://img.shields.io/badge/tests-949%20passed%20%C2%B7%2065%20skipped-brightgreen)](#testing)
[![Architecture](https://img.shields.io/badge/architecture-hexagonal-blueviolet)](#architecture)
[![License](https://img.shields.io/badge/license-proprietary-lightgrey)](#license)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Domain Model](#domain-model)
- [Mapping Strategies](#mapping-strategies)
- [Validation Pipeline](#validation-pipeline)
- [Persistence & Lifecycle](#persistence--lifecycle)
- [Batch Processing](#batch-processing)
- [Async Support](#async-support)
- [Observability](#observability)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview

`fault-mapper` is a **JSON-native pipeline platform** that takes structured document output from an upstream extraction system and produces validated S1000D Data Modules — the aerospace/defence standard for technical documentation. The platform currently supports **two module types**:

1. **Fault Data Modules** — fault reporting and isolation documentation (S1000D info codes `031`/`032`)
2. **Procedural Data Modules** — maintenance procedures, installation/removal tasks, inspection and servicing instructions (S1000D info codes `040`/`041`)

### What it does

```
DocumentPipelineOutput (JSON)
        |
        +-- Fault Pipeline (6-step)
        |   -> Section Selection (RULE -> LLM fallback)
        |   -> Fault Mode Routing (REPORTING or ISOLATION)
        |   -> Header Construction (deterministic rules)
        |   -> Content Mapping (LLM-driven with structured output)
        |   -> Module Assembly (deterministic -- no LLM, no I/O)
        |   -> 3-Layer Validation (structural -> schema -> business rules)
        |
        +-- Procedural Pipeline (7-step)
            -> Document Classification (RULE -> LLM fallback)
            -> Header Construction (deterministic rules)
            -> Section Organisation (classification + ordering)
            -> Step Extraction (LLM-assisted with nesting)
            -> Requirement Extraction (table headers -> LLM)
            -> Reference Extraction (regex -> LLM)
            -> Module Assembly (deterministic)
            -> 3-Layer Validation (structural -> schema -> business rules)

        Both pipelines share:
        -> Persistence (trusted / review collections)
        -> Review Workflow (approve / reject)
        -> Reconciliation (orphan sweep)
        -> Batch Processing (sync + async with bounded concurrency)
        -> Observability (metrics via MetricsSinkPort)
```

### Key properties

| Property | Detail |
|---|---|
| **Zero core dependencies** | Domain + application layers use only the Python stdlib |
| **Hexagonal architecture** | All I/O behind `typing.Protocol` port interfaces |
| **Two-pass strategy** | Deterministic rules first; LLM as semantic fallback |
| **Full provenance** | Every output field records its mapping strategy, source path, and confidence |
| **Staged trust** | APPROVED -> `trusted` collection; REVIEW_REQUIRED -> `review` collection |
| **Dual sync / async** | Both sync and async service variants for API and CLI deployments |
| **Batch support** | Process multiple documents in one call with per-item error isolation |
| **Multi-module** | Fault and Procedural pipelines share domain ports, value objects, and infrastructure |

---

## Architecture

**Hexagonal / Ports-and-Adapters** with clean onion layering.

Full C4 diagrams: [documents/architecture-c4.md](documents/architecture-c4.md)

### Domain Ports (Interfaces)

The system defines **12 Protocol interfaces** with **67 methods total**:

| Port | Methods | Scope | Purpose |
|---|---|---|---|
| `LlmInterpreterPort` | 7 | Fault | Semantic interpretation via LLM |
| `RulesEnginePort` | 14 | Fault | Deterministic rules and configuration |
| `MappingReviewPolicyPort` | 1 | Shared | Optional review-policy hook |
| `FaultModuleRepositoryPort` | 6 | Shared | Durable storage (CRUD) |
| `AuditRepositoryPort` | 2 | Shared | Audit event logging |
| `MetricsSinkPort` | 3 | Shared | Observability metrics |
| `TrustedModuleHandoffPort` | 1 | Shared | Post-approval downstream hook |
| `AsyncFaultModuleRepositoryPort` | 6 | Shared | Async durable storage |
| `AsyncAuditRepositoryPort` | 2 | Shared | Async audit logging |
| `AsyncLlmInterpreterPort` | 7 | Fault | Async LLM interpretation |
| `ProceduralLlmInterpreterPort` | 6 | Procedural | Procedural LLM interpretation |
| `ProceduralRulesEnginePort` | 12 | Procedural | Procedural deterministic rules |

---

## Project Structure

```
fault_mapper/                               84 source files
  domain/                                   Domain layer (zero external deps)
    enums.py                                FaultMode, ValidationStatus, ReviewStatus, ...
    models.py                               S1000DFaultDataModule, DocumentPipelineOutput, 40+ sub-models
    ports.py                                10 Protocol interfaces (shared + fault)
    value_objects.py                         Frozen dataclasses: DmCode, MappingTrace, BatchReport, ...
    procedural_enums.py                     ProceduralSectionType, StepType, ActionType, ProceduralModuleType
    procedural_models.py                    S1000DProceduralDataModule + 8 sub-models
    procedural_ports.py                     ProceduralLlmInterpreterPort, ProceduralRulesEnginePort
    procedural_value_objects.py             LLM interpretation VOs, ProceduralSectionLineage

  application/                              Application services
    _shared_helpers.py                      Pure helper functions
    fault_mapping_use_case.py               6-step fault orchestrator
    fault_section_selector.py               Two-pass RULE -> LLM section filtering
    fault_mode_router.py                    Two-pass RULE -> LLM mode determination
    fault_header_builder.py                 Rules-only DM header construction
    fault_reporting_mapper.py               LLM-driven fault-reporting content
    fault_isolation_mapper.py               LLM-driven isolation decision-tree
    fault_table_classifier.py               Two-pass RULE -> LLM table classification
    fault_schematic_correlator.py           Schematic-to-fault correlation
    fault_module_assembler.py               Deterministic final assembly
    fault_module_validator.py               Schema + business-rule + review gating
    fault_module_persistence_service.py     Sync persistence (trusted/review routing)
    fault_module_review_service.py          Approve / reject workflow
    fault_module_reconciliation_service.py  Orphan sweep
    fault_batch_processing_service.py       Sync batch processing
    async_persistence_service.py            Async fault persistence
    async_review_service.py                 Async fault review
    async_reconciliation_service.py         Async fault reconciliation
    async_fault_batch_processing_service.py Async fault batch (Semaphore-bounded)
    procedural_mapping_use_case.py          7-step procedural orchestrator
    procedural_document_classifier.py       Section filtering
    procedural_header_builder.py            DM header construction
    procedural_section_organizer.py         Section classification + ordering
    procedural_step_extractor.py            Step extraction + sub-step nesting
    procedural_requirement_extractor.py     Preliminary requirements
    procedural_reference_extractor.py       Cross-reference extraction
    procedural_module_assembler.py          Root aggregate assembly
    procedural_module_validator.py          Schema + business-rule + review gating
    procedural_module_persistence_service.py        Sync persistence
    procedural_batch_processing_service.py          Sync procedural batch
    async_procedural_module_persistence_service.py  Async procedural persistence
    async_procedural_batch_processing_service.py    Async procedural batch

  adapters/primary/
    api/
      app.py                                create_app() factory
      routes.py                             Fault: 9 endpoints
      dtos.py                               Fault Pydantic DTOs
      dependencies.py                       ServiceProvider / AsyncServiceProvider (fault)
      procedural_routes.py                  Procedural: 4 endpoints
      procedural_dtos.py                    Procedural Pydantic DTOs
      procedural_dependencies.py            ProceduralServiceProvider
    cli/
      main.py                               Fault Typer CLI (6 commands)
      procedural_main.py                    Procedural Typer CLI (2 commands)

  adapters/secondary/
    in_memory_repository.py                 FaultModuleRepositoryPort (dev/test)
    async_in_memory_repository.py           AsyncFaultModuleRepositoryPort
    mongodb_repository.py                   FaultModuleRepositoryPort (production)
    in_memory_audit_repository.py           AuditRepositoryPort
    async_in_memory_audit_repository.py     Async audit
    in_memory_metrics_sink.py               MetricsSinkPort
    llm_interpreter_adapter.py              LlmInterpreterPort
    rules_adapter.py                        RulesEnginePort
    module_serializer.py                    Fault -> camelCase JSON
    schema_validator.py                     JSON Schema 2020-12 validation
    structural_validator.py                 STRUCT-001..017 checks
    business_rule_validator.py              BIZ-001..012 checks
    review_gate.py                          Fault review decision logic
    instrumented_services.py                Sync fault metric-emitting wrappers
    async_instrumented_services.py          Async fault metric-emitting wrappers
    procedural_llm_interpreter_adapter.py   ProceduralLlmInterpreterPort
    procedural_rules_adapter.py             ProceduralRulesEnginePort
    procedural_module_serializer.py         Procedural -> JSON
    procedural_schema_validator.py          Procedural JSON Schema validation
    procedural_business_rule_validator.py   Procedural BIZ checks
    procedural_review_gate.py              Procedural review decision logic
    procedural_instrumented_services.py     Procedural metric wrappers

  infrastructure/
    config.py                               AppConfig (fault)
    factory.py                              FaultMapperFactory (composition root)
    procedural_config.py                    ProceduralAppConfig
    procedural_factory.py                   ProceduralMapperFactory (composition root)

  schemas/
    fault_data_module.schema.json           JSON Schema (Draft 2020-12, 33 $defs)

tests/                                      70 test files, 949 passed, 65 skipped
  conftest.py
  fakes/                                    9 test doubles
  fixtures/                                 4 fixture builder modules
  unit/                                     35 unit test files
  api/                                      2 API test files (fault + procedural)
  cli/                                      2 CLI test files (fault + procedural)
  integration/                              4 integration test files (MongoDB, E2E)
```

---

## Requirements

| Requirement | Version |
|---|---|
| **Python** | >= 3.11 |
| **FastAPI** | installed separately |
| **Typer** | installed separately |
| **Pydantic** | installed separately |
| **jsonschema** | installed separately |
| **uvicorn** | installed separately (HTTP server) |

### Optional

| Group | Packages | Purpose |
|---|---|---|
| `dev` | `pytest >= 8.0`, `pytest-cov >= 5.0`, `pytest-asyncio` | Testing and coverage |
| `mongo` | `pymongo >= 4.0` | MongoDB persistence adapter |
| `integration` | `pymongo >= 4.0`, `testcontainers[mongo] >= 4.0` | Docker-based integration tests |

---

## Installation

```bash
git clone <repository-url> fault_mapper
cd fault_mapper
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install fastapi uvicorn typer pydantic jsonschema
```

---

## Configuration

All configuration uses **frozen dataclasses with sensible defaults**. No config files required for development.

```python
from fault_mapper.infrastructure.config import AppConfig
config = AppConfig()  # All defaults

from fault_mapper.infrastructure.procedural_config import ProceduralAppConfig
proc_config = ProceduralAppConfig()  # info codes "040"/"041"
```

---

## Usage

### HTTP API

```bash
uvicorn fault_mapper.adapters.primary.api.app:app --reload
```

Interactive docs at `http://localhost:8000/docs`.

```bash
# Process a fault document
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"id": "doc-001", "full_text": "Fault content...", "file_name": "report.pdf"}'

# Process a procedural document
curl -X POST http://localhost:8000/procedural/process \
  -H "Content-Type: application/json" \
  -d '{"id": "proc-001", "full_text": "Remove and replace...", "file_name": "task.pdf"}'

# Batch processing (fault)
curl -X POST http://localhost:8000/process/batch \
  -H "Content-Type: application/json" \
  -d '{"items": [{"id": "d1", "full_text": "...", "file_name": "a.pdf"}]}'

# Batch processing (procedural)
curl -X POST http://localhost:8000/procedural/process/batch \
  -H "Content-Type: application/json" \
  -d '{"items": [{"id": "p1", "full_text": "...", "file_name": "b.pdf"}]}'
```

### CLI

```bash
# Fault commands
python -m fault_mapper.adapters.primary.cli.main health
python -m fault_mapper.adapters.primary.cli.main process input.json
python -m fault_mapper.adapters.primary.cli.main process-batch batch.json
python -m fault_mapper.adapters.primary.cli.main approve REC-001 --reason "Verified"
python -m fault_mapper.adapters.primary.cli.main reject REC-001 --reason "Incomplete"
python -m fault_mapper.adapters.primary.cli.main sweep --dry-run

# Procedural commands
python -m fault_mapper.adapters.primary.cli.procedural_main process-procedural input.json
python -m fault_mapper.adapters.primary.cli.procedural_main process-procedural-batch batch.json
```

---

## API Reference

### Fault Module Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/process` | Map + validate + persist one document |
| `POST` | `/process/batch` | Batch process multiple documents |
| `POST` | `/review/{id}/approve` | Approve a review-queue item |
| `POST` | `/review/{id}/reject` | Reject a review-queue item |
| `GET` | `/review/{id}` | Fetch a single review item |
| `GET` | `/review` | List review queue |
| `POST` | `/reconciliation/sweep` | Run reconciliation sweep |
| `GET` | `/reconciliation/orphans` | List orphaned review IDs |

### Procedural Module Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/procedural/process` | Map + validate + persist one procedural document |
| `POST` | `/procedural/process/batch` | Batch process multiple procedural documents |
| `GET` | `/procedural/review/{id}` | Fetch a single procedural review item |
| `GET` | `/procedural/review` | List procedural review queue |

### Error Responses

| Status | Meaning |
|---|---|
| `400` | No relevant sections found |
| `404` | Review item not found |
| `422` | Validation error or empty batch |
| `500` | Internal server error |
| `503` | Service unavailable (batch not configured) |

---

## Domain Model

### Fault Data Module (`S1000DFaultDataModule`)

| Field | Type | Description |
|---|---|---|
| `record_id` | `str` | Unique identifier |
| `mode` | `FaultMode` | `FAULT_REPORTING` or `FAULT_ISOLATION` |
| `header` | `FaultHeader` | DM identification (code, language, issue, title) |
| `content` | `FaultContent` | Mode-specific content block |
| `provenance` | `Provenance` | Source document linkage |
| `classification` | `Classification` | Method + confidence metadata |
| `trace` | `MappingTrace` | Per-field origin tracking |
| `validation_status` | `ValidationStatus` | Pipeline validation outcome |
| `review_status` | `ReviewStatus` | Review lifecycle state |

### Procedural Data Module (`S1000DProceduralDataModule`)

| Field | Type | Description |
|---|---|---|
| `record_id` | `str` | Unique identifier |
| `module_type` | `ProceduralModuleType` | `PROCEDURAL` or `DESCRIPTIVE` |
| `header` | `ProceduralHeader` | DM identification |
| `content` | `ProceduralContent` | Steps, sections, requirements, references |
| `provenance` | `Provenance` | Source document linkage |
| `classification` | `Classification` | Method + confidence metadata |
| `trace` | `MappingTrace` | Per-field origin tracking |
| `review_status` | `ReviewStatus` | Review lifecycle state |

### Lifecycle States

```
Fault:       PENDING -> validate() -> APPROVED / REVIEW_REQUIRED / SCHEMA_FAILED
                                        -> persist() -> trusted / review
                                        -> approve()/reject() -> trusted / REJECTED

Procedural:  NOT_REVIEWED -> validate() -> APPROVED / NOT_REVIEWED / REJECTED
                                            -> persist() -> procedural_trusted / procedural_review
```

---

## Mapping Strategies

**Two-pass strategy** for each interpretation task:

| Pass | Strategy | When Used | Cost |
|---|---|---|---|
| **1st** | `RULE` | Deterministic match succeeds | Free |
| **2nd** | `LLM` | Rule confidence below threshold | LLM API call |

Every output field records its origin in `MappingTrace.field_origins` with strategy, source path, and confidence.

### Fault Pipeline (6 Steps)

| Step | Component | Strategy | Output |
|---|---|---|---|
| 1 | `FaultSectionSelector` | RULE -> LLM | Relevant sections |
| 2 | `FaultModeRouter` | RULE -> LLM | REPORTING / ISOLATION |
| 3 | `FaultHeaderBuilder` | RULE only | `FaultHeader` |
| 4 | `FaultReportingMapper` / `FaultIsolationMapper` | LLM | Content block |
| 5 | `FaultModuleAssembler` | Deterministic | `S1000DFaultDataModule` |
| 6 | `FaultModuleValidator` | Rule-based | Validation + review |

### Procedural Pipeline (7 Steps)

| Step | Component | Strategy | Output |
|---|---|---|---|
| 1 | `ProceduralDocumentClassifier` | RULE -> LLM | Relevant sections |
| 2 | `ProceduralHeaderBuilder` | RULE only | `ProceduralHeader` |
| 3 | `ProceduralSectionOrganizer` | RULE -> LLM | Ordered sections |
| 4 | `ProceduralStepExtractor` | LLM-assisted | Step tree |
| 5 | `ProceduralRequirementExtractor` | Table -> LLM | Requirements |
| 6 | `ProceduralReferenceExtractor` | Regex -> LLM | Cross-references |
| 7 | `ProceduralModuleAssembler` | Deterministic | `S1000DProceduralDataModule` |

---

## Validation Pipeline

Three-layer validation (same pattern for both pipelines):

1. **Structural** -- hand-coded S1000D structural checks (`STRUCT-001..017`)
2. **Schema** -- JSON Schema Draft 2020-12 validation
3. **Business Rules** -- domain-specific checks (`BIZ-001..012`)

### Review Gate

```
Errors (any)           -> REJECTED
Warnings + low LLM     -> REVIEW_REQUIRED
Clean pass             -> APPROVED
```

---

## Persistence & Lifecycle

| Collection | Pipeline | Entry Criteria |
|---|---|---|
| `trusted` | Fault | APPROVED |
| `review` | Fault | REVIEW_REQUIRED |
| `procedural_trusted` | Procedural | APPROVED |
| `procedural_review` | Procedural | NOT_REVIEWED |
| `audit` | Both | Every approve / reject / sweep |

### Repository Adapters

| Adapter | Backend |
|---|---|
| `InMemoryFaultModuleRepository` | Python `dict` (dev/test) |
| `AsyncInMemoryFaultModuleRepository` | Async wrapper |
| `MongoDBFaultModuleRepository` | pymongo (production) |

---

## Batch Processing

Process multiple documents with **per-item error isolation**. Available for both fault and procedural pipelines in sync and async variants.

```python
# Sync
svc = FaultBatchProcessingService(use_case=uc, persistence=persistence)
report = svc.process_batch(items)  # -> BatchReport

# Async (bounded concurrency)
svc = AsyncFaultBatchProcessingService(use_case=uc, persistence=p, max_concurrency=5)
report = await svc.process_batch(items)  # -> BatchReport

# Same pattern for Procedural*BatchProcessingService
```

### BatchReport

```json
{
  "total": 10, "succeeded": 8, "failed": 2,
  "persisted_trusted": 6, "persisted_review": 2, "not_persisted": 2,
  "elapsed_ms": 1234.5,
  "items": [{"source_id": "doc-001", "success": true, "record_id": "REC-..."}]
}
```

---

## Async Support

| Sync Service | Async Service |
|---|---|
| `FaultModulePersistenceService` | `AsyncFaultModulePersistenceService` |
| `FaultModuleReviewService` | `AsyncFaultModuleReviewService` |
| `FaultModuleReconciliationService` | `AsyncFaultModuleReconciliationService` |
| `FaultBatchProcessingService` | `AsyncFaultBatchProcessingService` |
| `ProceduralModulePersistenceService` | `AsyncProceduralModulePersistenceService` |
| `ProceduralBatchProcessingService` | `AsyncProceduralBatchProcessingService` |

> **Note:** `FaultMappingUseCase` and `ProceduralMappingUseCase` are always sync (CPU-bound). In async contexts they run via `asyncio.to_thread()`.

---

## Observability

Instrumented wrappers emit metrics via `MetricsSinkPort`:

### Fault Metrics

| Metric | Type |
|---|---|
| `mapping.executed` / `mapping.duration_ms` / `mapping.failed` | Counter / Timing |
| `persistence.executed` / `persistence.duration_ms` | Counter / Timing |
| `review.approved` / `review.rejected` | Counter |
| `reconciliation.executed` / `reconciliation.duplicates_found` | Counter / Gauge |
| `batch.executed` / `batch.duration_ms` / `batch.total` / `batch.succeeded` / `batch.failed` | Counter / Timing / Gauge |

### Procedural Metrics

| Metric | Type |
|---|---|
| `procedural.mapping.executed` / `.duration_ms` / `.failure` | Counter / Timing |
| `procedural.persist.executed` / `.duration_ms` | Counter / Timing |
| `procedural.batch.executed` / `.duration_ms` / `.total` / `.succeeded` / `.failed` | Counter / Timing / Gauge |

---

## Testing

```bash
pytest                    # All tests
pytest tests/unit/        # Unit only
pytest tests/api/         # API only
pytest tests/cli/         # CLI only
pytest tests/integration/ # Integration (requires Docker)
```

| Category | Files | Description |
|---|---|---|
| Unit | 35 | All services, domain, adapters |
| API | 2 | Fault + procedural endpoints |
| CLI | 2 | Fault + procedural commands |
| Integration | 4 | MongoDB, E2E workflows |
| **Total** | **43** | **949 passed, 65 skipped** |

### Test Doubles

| Fake | Implements |
|---|---|
| `FakeLlmInterpreter` | `LlmInterpreterPort` |
| `FakeRulesEngine` | `RulesEnginePort` |
| `FakeMappingReviewPolicy` | `MappingReviewPolicyPort` |
| `FakeFaultModuleRepository` / `AsyncFake...` | `FaultModuleRepositoryPort` |
| `FakeAuditRepository` / `AsyncFake...` | `AuditRepositoryPort` |
| `FakeProceduralLlmInterpreter` | `ProceduralLlmInterpreterPort` |
| `FakeProceduralRulesEngine` | `ProceduralRulesEnginePort` |

---

## Roadmap

### Current State -- v0.9.0

| Module Type | Info Code | Status |
|---|---|---|
| Fault Data Module | `031` / `032` | Complete |
| Procedural Data Module | `040` / `041` | Complete |

### Future

| Module Type | Info Code | Status |
|---|---|---|
| Description Module | `040` -- `059` | Planned |
| Maintenance Planning Module | `020` -- `029` | Planned |
| Illustrated Parts Data Module | `060` -- `069` | Planned |
| Wiring Data Module | `070` -- `079` | Planned |

### Remaining Gaps

- Procedural review/reconciliation API (approve/reject)
- MongoDB async adapter (production)
- Top-level module-type router (auto-classify fault vs procedural)
- Batch size limits at API level
- Rate limiting / back-pressure

---

## License

Proprietary. All rights reserved.

---

> **v0.9.0** | Python >= 3.11 | Hexagonal Architecture | S1000D Fault + Procedural | 949 passed, 65 skipped
