# fault-mapper

> **Hybrid mapper that transforms `DocumentPipelineOutput` JSON into validated, canonical [S1000D](https://s1000d.org/) Fault Data Modules.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#requirements)
[![Tests](https://img.shields.io/badge/tests-563%20passed%20·%2065%20skipped-brightgreen)](#testing)
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
  - [HTTP API](#http-api)
  - [CLI](#cli)
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

`fault-mapper` is a **JSON-native pipeline** that takes structured document output from an upstream extraction system and produces validated S1000D Fault Data Modules — the aerospace/defence standard for fault reporting and isolation documentation.

### What it does

```
DocumentPipelineOutput (JSON)
  → Section Selection (RULE → LLM fallback)
  → Fault Mode Routing (REPORTING or ISOLATION)
  → Header Construction (deterministic rules)
  → Content Mapping (LLM-driven with structured output)
  → Module Assembly (deterministic — no LLM, no I/O)
  → 3-Layer Validation (structural → schema → business rules)
  → Persistence (trusted / review collections)
  → Review Workflow (approve / reject)
  → Reconciliation (orphan sweep)
```

### Key properties

| Property | Detail |
|---|---|
| **Zero core dependencies** | Domain + application layers use only the Python stdlib |
| **Hexagonal architecture** | All I/O behind `typing.Protocol` port interfaces |
| **Two-pass strategy** | Deterministic rules first; LLM as semantic fallback |
| **Full provenance** | Every output field records its mapping strategy, source path, and confidence |
| **Staged trust** | APPROVED → `trusted` collection; REVIEW_REQUIRED → `review` collection |
| **Dual sync / async** | Both sync and async service variants for API and CLI deployments |
| **Batch support** | Process multiple documents in one call with per-item error isolation |

---

## Architecture

**Hexagonal / Ports-and-Adapters** with clean onion layering:

```
┌─────────────────────────────────────────────────────┐
│  PRIMARY ADAPTERS (driving)                         │
│  ┌──────────────┐  ┌──────────────┐                │
│  │  FastAPI HTTP │  │  Typer CLI   │                │
│  └──────┬───────┘  └──────┬───────┘                │
│         │                  │                        │
│  ┌──────▼──────────────────▼───────────────────┐    │
│  │        APPLICATION SERVICES                  │    │
│  │  FaultMappingUseCase (6-step pipeline)       │    │
│  │  PersistenceService · ReviewService          │    │
│  │  ReconciliationService · BatchProcessing     │    │
│  │  ┌──────────────────────────────────────┐    │    │
│  │  │          DOMAIN                       │    │    │
│  │  │  Models · Enums · Value Objects       │    │    │
│  │  │  Port Interfaces (typing.Protocol)    │    │    │
│  │  └──────────────────────────────────────┘    │    │
│  └──────────────────────┬──────────────────────┘    │
│                         │                           │
│  ┌──────────────────────▼──────────────────────┐    │
│  │        SECONDARY ADAPTERS (driven)           │    │
│  │  LlmInterpreterAdapter · RulesAdapter        │    │
│  │  InMemoryRepository · MongoDBRepository      │    │
│  │  AuditRepository · MetricsSink               │    │
│  │  Serializer · Validators · ReviewGate        │    │
│  │  InstrumentedWrappers (decorator pattern)    │    │
│  └──────────────────────────────────────────────┘    │
│                                                     │
│  INFRASTRUCTURE (composition root)                  │
│  FaultMapperFactory · AppConfig                     │
└─────────────────────────────────────────────────────┘
```

> Full C4 diagrams: [`documents/architecture-c4.md`](documents/architecture-c4.md)

### Domain Ports (Interfaces)

| Port | Methods | Purpose |
|---|---|---|
| `LlmInterpreterPort` | 7 | Semantic interpretation via LLM |
| `RulesEnginePort` | 14 | Deterministic rules & configuration |
| `MappingReviewPolicyPort` | 1 | Optional review-policy hook |
| `FaultModuleRepositoryPort` | 6 | Durable storage (CRUD) |
| `AuditRepositoryPort` | 2 | Audit event logging |
| `MetricsSinkPort` | 3 | Observability metrics |
| `TrustedModuleHandoffPort` | 1 | Post-approval downstream hook |
| `AsyncFaultModuleRepositoryPort` | 6 | Async durable storage |
| `AsyncAuditRepositoryPort` | 2 | Async audit logging |
| `AsyncLlmInterpreterPort` | 7 | Async LLM interpretation |

---

## Project Structure

```
fault_mapper/
├── domain/                          # Domain layer (zero external deps)
│   ├── enums.py                     # FaultMode, ValidationStatus, ReviewStatus, …
│   ├── models.py                    # S1000DFaultDataModule, DocumentPipelineOutput, 40+ sub-models
│   ├── ports.py                     # 10 Protocol interfaces
│   └── value_objects.py             # Frozen dataclasses: DmCode, MappingTrace, BatchReport, …
│
├── application/                     # Application services
│   ├── fault_mapping_use_case.py    # 6-step orchestrator: select → route → header → map → assemble → validate
│   ├── fault_section_selector.py    # Two-pass RULE → LLM section filtering
│   ├── fault_mode_router.py         # Two-pass RULE → LLM mode determination
│   ├── fault_header_builder.py      # Rules-only DM header construction
│   ├── fault_reporting_mapper.py    # LLM-driven fault-reporting content extraction
│   ├── fault_isolation_mapper.py    # LLM-driven isolation decision-tree extraction
│   ├── fault_table_classifier.py    # Two-pass RULE → LLM table classification
│   ├── fault_schematic_correlator.py# Correlates schematics to fault entries
│   ├── fault_module_assembler.py    # Deterministic final assembly (no LLM, no I/O)
│   ├── fault_module_validator.py    # Schema + business-rule validation + review gating
│   ├── fault_module_persistence_service.py
│   ├── fault_module_review_service.py
│   ├── fault_module_reconciliation_service.py
│   ├── fault_batch_processing_service.py
│   ├── async_persistence_service.py
│   ├── async_review_service.py
│   ├── async_reconciliation_service.py
│   ├── async_fault_batch_processing_service.py
│   └── _shared_helpers.py           # Pure helper functions
│
├── adapters/
│   ├── primary/
│   │   ├── api/                     # FastAPI HTTP adapter
│   │   │   ├── app.py               # create_app() factory
│   │   │   ├── routes.py            # 9 endpoints across 4 routers
│   │   │   ├── dtos.py              # Pydantic request/response models
│   │   │   └── dependencies.py      # ServiceProvider / AsyncServiceProvider
│   │   └── cli/
│   │       └── main.py              # Typer CLI (6 commands)
│   │
│   └── secondary/
│       ├── llm_interpreter_adapter.py    # LlmInterpreterPort → OpenAI-compatible client
│       ├── rules_adapter.py              # RulesEnginePort → MappingConfig-driven rules
│       ├── in_memory_repository.py       # FaultModuleRepositoryPort (dev/test)
│       ├── async_in_memory_repository.py # AsyncFaultModuleRepositoryPort
│       ├── mongodb_repository.py         # FaultModuleRepositoryPort (production)
│       ├── in_memory_audit_repository.py # AuditRepositoryPort
│       ├── async_in_memory_audit_repository.py
│       ├── in_memory_metrics_sink.py     # MetricsSinkPort
│       ├── module_serializer.py          # S1000DFaultDataModule → camelCase JSON
│       ├── schema_validator.py           # JSON Schema 2020-12 validation
│       ├── structural_validator.py       # STRUCT-001..017 checks
│       ├── business_rule_validator.py    # BIZ-001..012 checks
│       ├── review_gate.py               # Review decision logic
│       ├── instrumented_services.py      # Sync metric-emitting decorators
│       └── async_instrumented_services.py# Async metric-emitting decorators
│
├── infrastructure/
│   ├── config.py                    # AppConfig (frozen dataclasses)
│   └── factory.py                   # FaultMapperFactory — composition root
│
└── schemas/
    └── fault_data_module.schema.json  # S1000D JSON Schema (Draft 2020-12, 33 $defs)

tests/
├── conftest.py                      # Shared fixtures & factory helpers
├── fakes/                           # Test doubles (7 modules)
│   ├── fake_llm_interpreter.py
│   ├── fake_rules_engine.py
│   ├── fake_mapping_review_policy.py
│   ├── fake_fault_module_repository.py
│   ├── async_fake_fault_module_repository.py
│   ├── fake_audit_repository.py
│   └── async_fake_audit_repository.py
├── fixtures/                        # Shared fixtures
│   ├── persistence_fixtures.py
│   └── validation_fixtures.py
├── unit/                            # 25 unit test files
├── api/                             # API route tests
├── cli/                             # CLI command tests
└── integration/                     # MongoDB + end-to-end tests
```

---

## Requirements

| Requirement | Version |
|---|---|
| **Python** | ≥ 3.11 |
| **FastAPI** | (installed separately) |
| **Typer** | (installed separately) |
| **Pydantic** | (installed separately) |
| **jsonschema** | (installed separately) |
| **uvicorn** | (installed separately, for HTTP server) |

### Optional

| Group | Packages | Purpose |
|---|---|---|
| `dev` | `pytest ≥ 8.0`, `pytest-cov ≥ 5.0` | Testing & coverage |
| `mongo` | `pymongo ≥ 4.0` | MongoDB persistence adapter |
| `integration` | `pymongo ≥ 4.0`, `testcontainers[mongo] ≥ 4.0` | Docker-based MongoDB integration tests |

---

## Installation

```bash
# Clone the repository
git clone <repository-url> fault_mapper
cd fault_mapper

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# (Optional) Install MongoDB support
pip install -e ".[mongo]"

# (Optional) Install integration test dependencies
pip install -e ".[integration]"

# Install HTTP / CLI framework dependencies
pip install fastapi uvicorn typer pydantic jsonschema
```

---

## Configuration

All configuration uses **frozen dataclasses with sensible defaults**. No config files are required for development — everything works out of the box with in-memory storage and default settings.

### `AppConfig`

```python
from fault_mapper.infrastructure.config import AppConfig

config = AppConfig()           # All defaults
config = AppConfig(
    llm=LlmConfig(
        provider="openai",     # "openai" | "anthropic" | "local"
        model="gpt-4o",
        temperature=0.0,
        max_tokens=4096,
        timeout_seconds=60,
        api_key="sk-...",
    ),
    mapping=MappingConfig(
        mapping_version="1.0.0",
        dm_code_defaults=DmCodeDefaults(
            model_ident_code="B737",
            system_code="29",
        ),
        thresholds=ThresholdConfig(
            fault_relevance=0.80,
            fault_mode=0.85,
        ),
    ),
    mongo=MongoConfig(
        connection_uri="mongodb://localhost:27017",
        database_name="fault_mapper",
    ),
)
```

### LLM Confidence Thresholds

| Task | Default | Description |
|---|---|---|
| `fault_relevance` | 0.80 | Section relevance assessment |
| `fault_mode` | 0.85 | REPORTING vs ISOLATION classification |
| `table_classification` | 0.80 | Table role determination |
| `fault_description` | 0.75 | Fault description extraction |
| `isolation_steps` | 0.75 | Decision tree extraction |
| `lru_sru` | 0.75 | Replaceable unit extraction |
| `schematic` | 0.70 | Schematic-to-fault correlation |

---

## Usage

### HTTP API

```bash
# Start the development server (in-memory, no LLM)
uvicorn fault_mapper.adapters.primary.api.app:app --reload

# Start with custom wiring
python -c "
from fault_mapper.adapters.primary.api.app import create_app
from fault_mapper.adapters.primary.api.dependencies import build_services

services = build_services(llm_client=my_llm, repository=my_repo)
app = create_app(services)
"
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

#### Example: Process a single document

```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{
    "id": "doc-001",
    "full_text": "Fault troubleshooting content...",
    "file_name": "B737-FaultReport.pdf"
  }'
```

#### Example: Process a batch

```bash
curl -X POST http://localhost:8000/process/batch \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"id": "doc-001", "full_text": "...", "file_name": "a.pdf"},
      {"id": "doc-002", "full_text": "...", "file_name": "b.pdf"}
    ]
  }'
```

### CLI

```bash
# Health check
python -m fault_mapper.adapters.primary.cli.main health

# Process a single document
python -m fault_mapper.adapters.primary.cli.main process input.json

# Process a batch of documents
python -m fault_mapper.adapters.primary.cli.main process-batch batch.json

# Approve a review item
python -m fault_mapper.adapters.primary.cli.main approve REC-001 --reason "Verified"

# Reject a review item
python -m fault_mapper.adapters.primary.cli.main reject REC-001 --reason "Incomplete data"

# Run a reconciliation sweep (dry run)
python -m fault_mapper.adapters.primary.cli.main sweep --dry-run

# Run a reconciliation sweep (live)
python -m fault_mapper.adapters.primary.cli.main sweep --limit 500
```

---

## API Reference

| Method | Path | Description | Request DTO | Response DTO |
|---|---|---|---|---|
| `GET` | `/health` | Health check | — | `HealthResponse` |
| `POST` | `/process` | Map + validate + persist one document | `ProcessRequest` | `ProcessResponse` |
| `POST` | `/process/batch` | Map + validate + persist multiple documents | `BatchProcessRequest` | `BatchProcessResponse` |
| `POST` | `/review/{id}/approve` | Approve a review-queue item | `ReviewActionRequest?` | `ReviewActionResponse` |
| `POST` | `/review/{id}/reject` | Reject a review-queue item | `ReviewActionRequest?` | `ReviewActionResponse` |
| `GET` | `/review/{id}` | Fetch a single review item | — | `ReviewItemResponse` |
| `GET` | `/review` | List review queue | `?limit=&offset=` | `ReviewListResponse` |
| `POST` | `/reconciliation/sweep` | Run reconciliation sweep | `SweepRequest?` | `SweepResponse` |
| `GET` | `/reconciliation/orphans` | List orphaned review IDs | — | `OrphansResponse` |

### Error Responses

All error responses use `ErrorResponse`:

```json
{
  "error": "Human-readable error message",
  "detail": "Optional technical detail"
}
```

| Status Code | Meaning |
|---|---|
| `400` | Bad request (e.g. no fault-relevant sections) |
| `404` | Review item not found |
| `422` | Validation error (Pydantic) |
| `500` | Internal server error |
| `503` | Service unavailable (LLM / batch not configured) |

---

## Domain Model

### Core Input

**`DocumentPipelineOutput`** — the normalised output from the upstream document extraction pipeline:

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique document identifier |
| `full_text` | `str` | Complete extracted text |
| `file_name` | `str` | Source file name |
| `file_type` | `str` | File format (pdf, html, …) |
| `source_path` | `str` | Original file path |
| `metadata` | `Metadata` | Upload + extraction metadata |
| `sections` | `list[Section]` | Structural sections with chunks, images, tables |
| `schematics` | `list[SchematicsItem]` | Extracted schematic diagrams |

### Core Output

**`S1000DFaultDataModule`** — the canonical S1000D fault data module:

| Field | Type | Description |
|---|---|---|
| `record_id` | `str` | Generated unique identifier |
| `mode` | `FaultMode` | `FAULT_REPORTING` or `FAULT_ISOLATION` |
| `header` | `FaultHeader` | DM identification (code, language, issue info, title) |
| `content` | `FaultContent` | Mode-specific content block |
| `provenance` | `Provenance` | Source document linkage |
| `classification` | `Classification` | Method + confidence metadata |
| `trace` | `MappingTrace` | Per-field origin tracking |
| `validation_status` | `ValidationStatus` | Pipeline validation outcome |
| `review_status` | `ReviewStatus` | Review lifecycle state |
| `validation_results` | `ValidationResults` | Detailed issue lists |
| `mapping_version` | `str` | Schema / pipeline version |

### Lifecycle States

```
              ┌──────────┐
              │ PENDING   │
              └────┬─────┘
                   │ validate()
        ┌──────────┼──────────┐
        ▼          ▼          ▼
  ┌──────────┐ ┌────────┐ ┌───────────────┐
  │ APPROVED │ │REVIEW_ │ │ SCHEMA_FAILED │
  │          │ │REQUIRED│ │ BIZ_RULE_FAIL │
  └────┬─────┘ └───┬────┘ │ COMPLETENESS_ │
       │            │      │ FAILED        │
       │ persist()  │      └───────────────┘
       ▼            ▼
  ┌────────┐   ┌────────┐
  │trusted │   │ review │
  │  coll. │   │  coll. │
  └────────┘   └───┬────┘
                   │ approve() / reject()
              ┌────┴────┐
              ▼         ▼
         ┌────────┐ ┌──────────┐
         │trusted │ │ REJECTED │
         │  coll. │ │ (stays   │
         └────────┘ │  review) │
                    └──────────┘
```

---

## Mapping Strategies

The pipeline uses a **two-pass strategy** for each interpretation task:

| Pass | Strategy | When Used | Cost |
|---|---|---|---|
| **1st** | `RULE` | Deterministic keyword/heuristic match succeeds | Free |
| **2nd** | `LLM` | Rule confidence below threshold | LLM API call |

Every output field records its origin in `MappingTrace.field_origins`:

```python
FieldOrigin(
    strategy=MappingStrategy.LLM,      # DIRECT | RULE | LLM
    source_path="sections[2].text",
    confidence=0.92,
)
```

### Pipeline Steps

| Step | Component | Strategy | Output |
|---|---|---|---|
| 1. Section Selection | `FaultSectionSelector` | RULE → LLM | Relevant sections |
| 2. Mode Routing | `FaultModeRouter` | RULE → LLM | `FAULT_REPORTING` / `FAULT_ISOLATION` |
| 3. Header Building | `FaultHeaderBuilder` | RULE only | `FaultHeader` (DM code, language, title) |
| 4a. Reporting Mapping | `FaultReportingMapper` | LLM | `FaultReportingContent` |
| 4b. Isolation Mapping | `FaultIsolationMapper` | LLM | `FaultIsolationContent` |
| 5. Assembly | `FaultModuleAssembler` | Deterministic | `S1000DFaultDataModule` |
| 6. Validation | `FaultModuleValidator` | Rule-based | Validation status + review decision |

---

## Validation Pipeline

Three-layer validation with configurable review gating:

### Layer 1 — Structural Validation (`STRUCT-001` .. `STRUCT-017`)

Hand-coded checks for S1000D structural requirements:
- Required fields present
- Mode-content consistency
- DM code format
- Fault entry completeness

### Layer 2 — Schema Validation

JSON Schema Draft 2020-12 validation against `fault_data_module.schema.json` (33 `$defs`, 786 lines).

### Layer 3 — Business Rule Validation (`BIZ-001` .. `BIZ-012`)

Domain-specific checks:
- Fault code uniqueness
- LRU/SRU reference validity
- Isolation step tree integrity
- Detection-repair consistency

### Review Gate

```
Errors (any)         → REJECTED
Warnings + low LLM   → REVIEW_REQUIRED (NOT_REVIEWED)
Clean pass           → APPROVED
```

---

## Persistence & Lifecycle

### Collections

| Collection | Contents | Entry Criteria |
|---|---|---|
| `trusted` | Approved fault modules | `validation_status == APPROVED` or manual approval |
| `review` | Flagged modules awaiting review | `validation_status == REVIEW_REQUIRED` |
| `audit` | Immutable event log | Every approve / reject / sweep action |

### Repository Adapters

| Adapter | Port | Backend |
|---|---|---|
| `InMemoryFaultModuleRepository` | `FaultModuleRepositoryPort` | Python `dict` (dev/test) |
| `AsyncInMemoryFaultModuleRepository` | `AsyncFaultModuleRepositoryPort` | Async wrapper |
| `MongoDBFaultModuleRepository` | `FaultModuleRepositoryPort` | pymongo (production) |

### Review Workflow

```bash
# List items pending review
GET /review?limit=50

# Approve (moves to trusted, records audit entry)
POST /review/REC-001/approve
  {"reason": "Verified against source", "performed_by": "engineer-42"}

# Reject (stays in review with REJECTED status, records audit entry)
POST /review/REC-001/reject
  {"reason": "Missing fault codes", "performed_by": "engineer-42"}
```

### Reconciliation

Detects orphaned entries (present in both `review` and `trusted`) and cleans them:

```bash
# Preview what would be cleaned
POST /reconciliation/sweep  {"dry_run": true}

# Execute cleanup
POST /reconciliation/sweep  {"dry_run": false, "limit": 1000}

# List orphans directly
GET /reconciliation/orphans
```

---

## Batch Processing

Process multiple documents in a single call with **per-item error isolation** — one failing document does not block the rest.

### Sync (Sequential)

```python
from fault_mapper.application.fault_batch_processing_service import (
    FaultBatchProcessingService,
)

svc = FaultBatchProcessingService(use_case=uc, persistence=persistence)
report = svc.process_batch(items)  # → BatchReport
```

### Async (Bounded Concurrency)

```python
from fault_mapper.application.async_fault_batch_processing_service import (
    AsyncFaultBatchProcessingService,
)

svc = AsyncFaultBatchProcessingService(
    use_case=uc,
    persistence=async_persistence,
    max_concurrency=5,  # asyncio.Semaphore bound
)
report = await svc.process_batch(items)  # → BatchReport
```

### BatchReport

```json
{
  "total": 10,
  "succeeded": 8,
  "failed": 2,
  "persisted_trusted": 6,
  "persisted_review": 2,
  "not_persisted": 2,
  "elapsed_ms": 1234.5,
  "items": [
    {
      "source_id": "doc-001",
      "success": true,
      "record_id": "REC-doc-001",
      "validation_status": "APPROVED",
      "review_status": "APPROVED",
      "collection": "trusted",
      "persisted": true,
      "error": null
    }
  ]
}
```

---

## Async Support

Every lifecycle service has a full **async mirror**:

| Sync Service | Async Service |
|---|---|
| `FaultModulePersistenceService` | `AsyncFaultModulePersistenceService` |
| `FaultModuleReviewService` | `AsyncFaultModuleReviewService` |
| `FaultModuleReconciliationService` | `AsyncFaultModuleReconciliationService` |
| `FaultBatchProcessingService` | `AsyncFaultBatchProcessingService` |

The API layer auto-detects which provider type is injected (`ServiceProvider` vs `AsyncServiceProvider`) and dispatches accordingly.

> **Note:** `FaultMappingUseCase` is always sync (CPU-bound). In async contexts it runs via `asyncio.to_thread()`.

---

## Observability

All services can be wrapped with **instrumented decorators** that emit metrics via `MetricsSinkPort`:

| Metric | Type | Emitted By |
|---|---|---|
| `mapping.executed` | Counter | `InstrumentedFaultMappingUseCase` |
| `mapping.duration_ms` | Timing | `InstrumentedFaultMappingUseCase` |
| `mapping.failed` | Counter | `InstrumentedFaultMappingUseCase` |
| `persistence.executed` | Counter | `InstrumentedFaultModulePersistenceService` |
| `persistence.duration_ms` | Timing | `InstrumentedFaultModulePersistenceService` |
| `review.approved` | Counter | `InstrumentedFaultModuleReviewService` |
| `review.rejected` | Counter | `InstrumentedFaultModuleReviewService` |
| `review.not_found` | Counter | `InstrumentedFaultModuleReviewService` |
| `reconciliation.executed` | Counter | `InstrumentedFaultModuleReconciliationService` |
| `reconciliation.duplicates_found` | Gauge | `InstrumentedFaultModuleReconciliationService` |
| `batch.executed` | Counter | `InstrumentedFaultBatchProcessingService` |
| `batch.duration_ms` | Timing | `InstrumentedFaultBatchProcessingService` |
| `batch.total` / `.succeeded` / `.failed` | Gauge | `InstrumentedFaultBatchProcessingService` |

Instrumented wrappers are applied automatically by `FaultMapperFactory` when a `MetricsSinkPort` is provided. The `InMemoryMetricsSink` captures all metrics for test assertions.

---

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=fault_mapper --cov-report=term-missing

# Run only unit tests
pytest tests/unit/

# Run API tests
pytest tests/api/

# Run CLI tests
pytest tests/cli/

# Run integration tests (requires Docker for MongoDB)
pytest tests/integration/

# Run a specific test file
pytest tests/unit/test_fault_batch_processing_service.py -v
```

### Test Suite Summary

| Category | Files | Description |
|---|---|---|
| **Unit** | 25 | All application services, domain logic, adapters |
| **API** | 1 | FastAPI `TestClient` tests for all endpoints |
| **CLI** | 1 | Typer `CliRunner` tests for all commands |
| **Integration** | 3 | MongoDB (Testcontainers), end-to-end workflows |
| **Total** | **30 files** | **563 passed, 65 skipped** |

### Test Doubles

| Fake | Implements | Purpose |
|---|---|---|
| `FakeLlmInterpreter` | `LlmInterpreterPort` | Returns canned LLM responses |
| `FakeRulesEngine` | `RulesEnginePort` | Returns configurable rule results |
| `FakeMappingReviewPolicy` | `MappingReviewPolicyPort` | Configurable review decisions |
| `FakeFaultModuleRepository` | `FaultModuleRepositoryPort` | Dict-backed with inspection hooks |
| `AsyncFakeFaultModuleRepository` | `AsyncFaultModuleRepositoryPort` | Async variant |
| `FakeAuditRepository` | `AuditRepositoryPort` | List-backed with inspection |
| `AsyncFakeAuditRepository` | `AsyncAuditRepositoryPort` | Async variant |

---

## Roadmap

### Current State — Single Module (`v0.1.0`)

The system currently produces **one module type**: S1000D Fault Data Modules (`FAULT_REPORTING` and `FAULT_ISOLATION` modes).

### Future State — Multi Module

Planned expansion to additional S1000D data module types:

| Module Type | S1000D Info Code | Status |
|---|---|---|
| **Fault Data Module** | `031` (Reporting), `032` (Isolation) | ✅ Implemented |
| Description Module | `040` – `059` | 🔮 Planned |
| Maintenance Planning Module | `020` – `029` | 🔮 Planned |
| Illustrated Parts Data Module | `060` – `069` | 🔮 Planned |
| Wiring Data Module | `070` – `079` | 🔮 Planned |
| Crew/Operator Module | `080` – `089` | 🔮 Planned |

The hexagonal architecture is designed to support this evolution:

- **Domain ports** are module-type agnostic — `FaultModuleRepositoryPort` generalises to `DataModuleRepositoryPort`
- **Factory pattern** allows adding new use cases (`DescriptionMappingUseCase`, etc.) without modifying existing ones
- **Mode router** concept extends to a **module type router** for multi-module classification
- **Shared infrastructure** (persistence, review, reconciliation, batch, metrics) is reusable across all module types
- **Per-module mappers** follow the same internal pattern (section selection → content mapping → assembly → validation)

---

## License

Proprietary. All rights reserved.

---

> **Version**: 0.1.0 · **Python**: ≥ 3.11 · **Architecture**: Hexagonal / Ports-and-Adapters · **Module**: S1000D Fault Data Module
