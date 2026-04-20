# fault-mapper Architecture (C4 Model)

> Detailed C4 architecture diagrams for the fault-mapper platform.
> Version 0.9.0 | Dual-module: Fault + Procedural

---

## C4 Level 1 -- System Context

```mermaid
C4Context
    title System Context Diagram -- fault-mapper

    Person(engineer, "Technical Author / Engineer", "Reviews and approves generated S1000D data modules")

    System(faultMapper, "fault-mapper", "Transforms extracted document JSON into validated S1000D Fault and Procedural Data Modules")

    System_Ext(extractionPipeline, "Document Extraction Pipeline", "Upstream system that produces DocumentPipelineOutput JSON from PDFs/HTML")
    System_Ext(llmProvider, "LLM Provider", "OpenAI-compatible API for semantic interpretation fallback")
    System_Ext(mongodb, "MongoDB", "Persistent storage for trusted/review module collections")
    System_Ext(downstream, "Downstream Consumers", "IETM publishing, CSDB, or other S1000D-consuming systems")

    Rel(extractionPipeline, faultMapper, "Sends DocumentPipelineOutput JSON", "HTTP / CLI")
    Rel(faultMapper, llmProvider, "Semantic interpretation requests", "HTTPS / API key")
    Rel(faultMapper, mongodb, "Reads/writes module records", "pymongo")
    Rel(faultMapper, downstream, "Hands off trusted modules", "TrustedModuleHandoffPort")
    Rel(engineer, faultMapper, "Reviews, approves/rejects modules", "HTTP API / CLI")
```

### Key Interactions

| From | To | Protocol | Data |
|---|---|---|---|
| Extraction Pipeline | fault-mapper | HTTP POST / CLI stdin | `DocumentPipelineOutput` JSON |
| fault-mapper | LLM Provider | HTTPS | Structured prompts, JSON responses |
| fault-mapper | MongoDB | pymongo TCP | Module CRUD, audit events |
| fault-mapper | Downstream | `TrustedModuleHandoffPort` | Approved `S1000DFaultDataModule` / `S1000DProceduralDataModule` |
| Engineer | fault-mapper | HTTP / CLI | Review actions (approve/reject/sweep) |

---

## C4 Level 2 -- Container Diagram

```mermaid
C4Container
    title Container Diagram -- fault-mapper

    Person(engineer, "Engineer")

    System_Boundary(fm, "fault-mapper") {
        Container(api, "FastAPI HTTP Server", "Python, FastAPI, uvicorn", "Exposes 13 REST endpoints for fault + procedural processing, review, and reconciliation")
        Container(cli, "Typer CLI", "Python, Typer", "Command-line interface with 8 commands across fault and procedural pipelines")
        Container(appCore, "Application Core", "Pure Python", "Use cases, services, domain models, port interfaces. Zero external dependencies.")
        Container(adapters, "Secondary Adapters", "Python", "LLM clients, rules engines, repositories, validators, serializers, instrumented wrappers")
        Container(infra, "Infrastructure", "Python", "Composition roots (factories), configuration dataclasses")
    }

    System_Ext(llm, "LLM Provider")
    System_Ext(mongo, "MongoDB")
    System_Ext(downstream, "Downstream")

    Rel(engineer, api, "HTTP requests")
    Rel(engineer, cli, "CLI commands")
    Rel(api, appCore, "Calls use cases and services")
    Rel(cli, appCore, "Calls use cases and services")
    Rel(appCore, adapters, "Via port interfaces (typing.Protocol)")
    Rel(adapters, llm, "LLM API calls")
    Rel(adapters, mongo, "pymongo CRUD")
    Rel(appCore, downstream, "TrustedModuleHandoffPort")
    Rel(infra, appCore, "Wires dependencies")
    Rel(infra, adapters, "Instantiates adapters")
```

### Container Inventory

| Container | Technology | Files | Responsibility |
|---|---|---|---|
| **FastAPI HTTP** | FastAPI + Pydantic | 7 files | REST API (9 fault + 4 procedural endpoints) |
| **Typer CLI** | Typer | 2 files | CLI (6 fault + 2 procedural commands) |
| **Application Core** | Pure Python | 32 files | Use cases, services, domain models, ports |
| **Secondary Adapters** | Python | 21 files | LLM, rules, repos, validators, serializers, metrics |
| **Infrastructure** | Python | 4 files | Factories, config dataclasses |

---

## C4 Level 3 -- Component Diagram (Application Core)

```mermaid
C4Component
    title Component Diagram -- Application Core

    Container_Boundary(app, "Application Core") {

        Component(faultUC, "FaultMappingUseCase", "6-step orchestrator", "Coordinates section selection, mode routing, header building, content mapping, assembly, validation")
        Component(procUC, "ProceduralMappingUseCase", "7-step orchestrator", "Coordinates classification, header, sections, steps, requirements, references, assembly")

        Component(faultPersist, "FaultModulePersistenceService", "Sync persistence", "Routes APPROVED->trusted, REVIEW_REQUIRED->review")
        Component(faultReview, "FaultModuleReviewService", "Review workflow", "Approve/reject with audit trail")
        Component(faultRecon, "FaultModuleReconciliationService", "Orphan sweep", "Finds and purges orphaned review records")
        Component(faultBatch, "FaultBatchProcessingService", "Sync batch", "Sequential processing with per-item isolation")

        Component(procPersist, "ProceduralModulePersistenceService", "Sync persistence", "Routes APPROVED->procedural_trusted, NOT_REVIEWED->procedural_review")
        Component(procBatch, "ProceduralBatchProcessingService", "Sync batch", "Sequential processing with per-item isolation")

        Component(asyncFaultPersist, "AsyncFaultModulePersistenceService", "Async persistence", "Async variant of fault persistence")
        Component(asyncFaultReview, "AsyncFaultModuleReviewService", "Async review", "Async variant of fault review")
        Component(asyncFaultRecon, "AsyncFaultModuleReconciliationService", "Async reconciliation", "Async variant")
        Component(asyncFaultBatch, "AsyncFaultBatchProcessingService", "Async batch", "Semaphore-bounded concurrent processing")

        Component(asyncProcPersist, "AsyncProceduralModulePersistenceService", "Async persistence", "Async procedural persistence")
        Component(asyncProcBatch, "AsyncProceduralBatchProcessingService", "Async batch", "Semaphore-bounded concurrent processing")

        Component(domain, "Domain Layer", "Models + Ports + Value Objects", "S1000DFaultDataModule, S1000DProceduralDataModule, 12 Protocol interfaces, enums, frozen VOs")
    }

    Rel(faultUC, domain, "Creates S1000DFaultDataModule")
    Rel(procUC, domain, "Creates S1000DProceduralDataModule")
    Rel(faultBatch, faultUC, "Delegates per-item")
    Rel(faultBatch, faultPersist, "Persists results")
    Rel(procBatch, procUC, "Delegates per-item")
    Rel(procBatch, procPersist, "Persists results")
    Rel(asyncFaultBatch, faultUC, "via asyncio.to_thread()")
    Rel(asyncProcBatch, procUC, "via asyncio.to_thread()")
```

---

## C4 Level 3 -- Component Diagram (Secondary Adapters)

```mermaid
C4Component
    title Component Diagram -- Secondary Adapters

    Container_Boundary(sec, "Secondary Adapters") {

        ComponentDb(inMemRepo, "InMemoryFaultModuleRepository", "dict-backed", "Dev/test repository")
        ComponentDb(asyncInMemRepo, "AsyncInMemoryFaultModuleRepository", "async dict", "Async dev/test repository")
        ComponentDb(mongoRepo, "MongoDBFaultModuleRepository", "pymongo", "Production repository")
        ComponentDb(auditRepo, "InMemoryAuditRepository", "list-backed", "Audit event storage")

        Component(llmAdapter, "LlmInterpreterAdapter", "OpenAI-compatible", "Fault LLM interpretation (7 methods)")
        Component(rulesAdapter, "RulesAdapter", "MappingConfig", "Fault deterministic rules (14 methods)")
        Component(procLlmAdapter, "ProceduralLlmInterpreterAdapter", "OpenAI-compatible", "Procedural LLM (6 methods)")
        Component(procRulesAdapter, "ProceduralRulesAdapter", "Config-driven", "Procedural rules (12 methods)")

        Component(structValidator, "StructuralValidator", "Rule-based", "STRUCT-001..017")
        Component(schemaValidator, "SchemaValidator", "jsonschema", "Draft 2020-12")
        Component(bizValidator, "BusinessRuleValidator", "Rule-based", "BIZ-001..012")
        Component(reviewGate, "ReviewGate", "Decision logic", "APPROVED / REVIEW_REQUIRED / REJECTED")

        Component(procSchemaVal, "ProceduralSchemaValidator", "jsonschema", "Procedural schema validation")
        Component(procBizVal, "ProceduralBusinessRuleValidator", "Rule-based", "Procedural BIZ checks")
        Component(procReviewGate, "ProceduralReviewGate", "Decision logic", "Procedural review decisions")

        Component(serializer, "ModuleSerializer", "camelCase JSON", "Fault module serialization")
        Component(procSerializer, "ProceduralModuleSerializer", "JSON", "Procedural module serialization")

        Component(instrFault, "InstrumentedServices", "Decorator pattern", "Sync fault metric wrappers")
        Component(asyncInstrFault, "AsyncInstrumentedServices", "Decorator pattern", "Async fault metric wrappers")
        Component(instrProc, "ProceduralInstrumentedServices", "Decorator pattern", "Procedural metric wrappers")

        Component(metricsSink, "InMemoryMetricsSink", "dict-backed", "Captures counter/timing/gauge metrics")
    }
```

---

## C4 Level 3 -- Component Diagram (Fault Pipeline Detail)

```mermaid
flowchart LR
    subgraph "Fault Pipeline (6 Steps)"
        A[FaultSectionSelector] -->|relevant sections| B[FaultModeRouter]
        B -->|FaultMode| C[FaultHeaderBuilder]
        C -->|FaultHeader| D{Mode?}
        D -->|REPORTING| E[FaultReportingMapper]
        D -->|ISOLATION| F[FaultIsolationMapper]
        E -->|FaultReportingContent| G[FaultModuleAssembler]
        F -->|FaultIsolationContent| G
        G -->|S1000DFaultDataModule| H[FaultModuleValidator]
    end

    subgraph "Supporting Services"
        I[FaultTableClassifier]
        J[FaultSchematicCorrelator]
    end

    E -.->|classifies tables| I
    E -.->|correlates schematics| J
    F -.->|classifies tables| I

    subgraph "Validation Layers"
        H1[StructuralValidator]
        H2[SchemaValidator]
        H3[BusinessRuleValidator]
        H4[ReviewGate]
    end

    H --> H1 --> H2 --> H3 --> H4
```

---

## C4 Level 3 -- Component Diagram (Procedural Pipeline Detail)

```mermaid
flowchart LR
    subgraph "Procedural Pipeline (7 Steps)"
        A[ProceduralDocumentClassifier] -->|relevant sections| B[ProceduralHeaderBuilder]
        B -->|ProceduralHeader| C[ProceduralSectionOrganizer]
        C -->|ordered sections| D[ProceduralStepExtractor]
        D -->|step tree| E[ProceduralRequirementExtractor]
        E -->|requirements| F[ProceduralReferenceExtractor]
        F -->|references| G[ProceduralModuleAssembler]
    end

    subgraph "Validation"
        V1[ProceduralSchemaValidator]
        V2[ProceduralBusinessRuleValidator]
        V3[ProceduralReviewGate]
    end

    G -->|S1000DProceduralDataModule| V1 --> V2 --> V3
```

---

## C4 Level 4 -- Code Diagram (Domain Model)

```mermaid
classDiagram
    class DocumentPipelineOutput {
        +str id
        +str full_text
        +str file_name
        +str file_type
        +str source_path
        +Metadata metadata
        +list~Section~ sections
        +list~SchematicsItem~ schematics
    }

    class S1000DFaultDataModule {
        +str record_id
        +FaultMode mode
        +FaultHeader header
        +FaultContent content
        +Provenance provenance
        +Classification classification
        +MappingTrace trace
        +ValidationStatus validation_status
        +ReviewStatus review_status
        +ValidationResults validation_results
        +str mapping_version
    }

    class S1000DProceduralDataModule {
        +str record_id
        +ProceduralModuleType module_type
        +ProceduralHeader header
        +ProceduralContent content
        +Provenance provenance
        +Classification classification
        +MappingTrace trace
        +ReviewStatus review_status
        +ProceduralValidationResults validation_results
        +str mapping_version
    }

    class FaultMode {
        <<enumeration>>
        FAULT_REPORTING
        FAULT_ISOLATION
    }

    class ProceduralModuleType {
        <<enumeration>>
        PROCEDURAL
        DESCRIPTIVE
    }

    class ValidationStatus {
        <<enumeration>>
        PENDING
        APPROVED
        REVIEW_REQUIRED
        SCHEMA_FAILED
        BIZ_RULE_FAILED
    }

    class ReviewStatus {
        <<enumeration>>
        PENDING
        APPROVED
        REJECTED
        REVIEW_REQUIRED
        NOT_REVIEWED
    }

    class MappingTrace {
        +dict~str,FieldOrigin~ field_origins
    }

    class FieldOrigin {
        +MappingStrategy strategy
        +str source_path
        +float confidence
    }

    class BatchReport {
        +int total
        +int succeeded
        +int failed
        +int persisted_trusted
        +int persisted_review
        +int not_persisted
        +float elapsed_ms
        +list~BatchItem~ items
    }

    S1000DFaultDataModule --> FaultMode
    S1000DFaultDataModule --> ValidationStatus
    S1000DFaultDataModule --> ReviewStatus
    S1000DFaultDataModule --> MappingTrace
    S1000DProceduralDataModule --> ProceduralModuleType
    S1000DProceduralDataModule --> ReviewStatus
    S1000DProceduralDataModule --> MappingTrace
    MappingTrace --> FieldOrigin
```

---

## C4 Level 4 -- Code Diagram (Port Interfaces)

```mermaid
classDiagram
    class LlmInterpreterPort {
        <<Protocol>>
        +assess_fault_relevance(section) RelevanceResult
        +determine_fault_mode(sections) FaultModeResult
        +extract_fault_descriptions(sections) list
        +extract_isolation_steps(sections) list
        +extract_lru_sru(sections) list
        +correlate_schematics(schematics, sections) list
        +classify_table(table) TableClassification
    }

    class RulesEnginePort {
        <<Protocol>>
        +check_fault_keywords(section) KeywordResult
        +determine_fault_mode_by_rules(sections) FaultModeResult
        +build_dm_code(input, mode) DmCode
        +14 methods total
    }

    class ProceduralLlmInterpreterPort {
        <<Protocol>>
        +assess_procedural_relevance(section) RelevanceResult
        +classify_section_type(section) SectionTypeResult
        +extract_steps(section) list~ProceduralStep~
        +extract_requirements(section) PreliminaryRequirements
        +extract_references(section) list~Reference~
        +determine_module_type(sections) ModuleTypeResult
    }

    class ProceduralRulesEnginePort {
        <<Protocol>>
        +check_procedural_keywords(section) KeywordResult
        +classify_section_by_rules(section) SectionTypeResult
        +build_procedural_dm_code(input, type) DmCode
        +12 methods total
    }

    class FaultModuleRepositoryPort {
        <<Protocol>>
        +save_trusted(module) str
        +save_review(module) str
        +find_by_id(id) Module?
        +find_review_items(limit, offset) list
        +delete_review(id) bool
        +count_review() int
    }

    class MetricsSinkPort {
        <<Protocol>>
        +increment(name, value, tags)
        +timing(name, ms, tags)
        +gauge(name, value, tags)
    }

    class AuditRepositoryPort {
        <<Protocol>>
        +record_event(event) None
        +find_events(filter) list
    }
```

---

## Deployment View

```mermaid
flowchart TB
    subgraph "Development"
        DEV_API[FastAPI + uvicorn]
        DEV_CLI[Typer CLI]
        DEV_REPO[(InMemoryRepository)]
        DEV_METRICS[(InMemoryMetricsSink)]
    end

    subgraph "Production"
        PROD_API[FastAPI + gunicorn/uvicorn]
        PROD_CLI[Typer CLI]
        PROD_MONGO[(MongoDB)]
        PROD_LLM[OpenAI API]
        PROD_METRICS[Prometheus / Datadog]
    end

    DEV_API --> DEV_REPO
    DEV_CLI --> DEV_REPO
    DEV_API --> DEV_METRICS

    PROD_API --> PROD_MONGO
    PROD_CLI --> PROD_MONGO
    PROD_API --> PROD_LLM
    PROD_CLI --> PROD_LLM
    PROD_API --> PROD_METRICS
```

---

## Data Flow -- Fault Module Processing

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant UC as FaultMappingUseCase
    participant LLM as LlmInterpreterPort
    participant Rules as RulesEnginePort
    participant Val as FaultModuleValidator
    participant Persist as PersistenceService
    participant Repo as RepositoryPort
    participant Audit as AuditRepositoryPort

    Client->>API: POST /process {DocumentPipelineOutput}
    API->>UC: execute(input)
    UC->>Rules: check_fault_keywords(section)
    alt Rule confidence < threshold
        UC->>LLM: assess_fault_relevance(section)
    end
    UC->>Rules: determine_fault_mode_by_rules(sections)
    alt Rule confidence < threshold
        UC->>LLM: determine_fault_mode(sections)
    end
    UC->>Rules: build_dm_code(input, mode)
    UC->>LLM: extract_fault_descriptions(sections)
    UC->>UC: assemble(header, content, provenance, trace)
    UC-->>API: S1000DFaultDataModule
    API->>Val: validate(module)
    Val-->>API: ValidationResults
    API->>Persist: persist(module)
    alt APPROVED
        Persist->>Repo: save_trusted(module)
    else REVIEW_REQUIRED
        Persist->>Repo: save_review(module)
    end
    Persist->>Audit: record_event(persistence_event)
    API-->>Client: ProcessResponse
```

---

## Data Flow -- Procedural Module Processing

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant UC as ProceduralMappingUseCase
    participant LLM as ProceduralLlmInterpreterPort
    participant Rules as ProceduralRulesEnginePort
    participant Val as ProceduralModuleValidator
    participant Persist as ProceduralPersistenceService
    participant Repo as RepositoryPort

    Client->>API: POST /procedural/process {DocumentPipelineOutput}
    API->>UC: execute(input)
    UC->>Rules: check_procedural_keywords(section)
    alt Rule confidence < threshold
        UC->>LLM: assess_procedural_relevance(section)
    end
    UC->>Rules: build_procedural_dm_code(input, type)
    UC->>Rules: classify_section_by_rules(section)
    alt Rule confidence < threshold
        UC->>LLM: classify_section_type(section)
    end
    UC->>LLM: extract_steps(section)
    UC->>LLM: extract_requirements(section)
    UC->>LLM: extract_references(section)
    UC->>UC: assemble(header, content, provenance, trace)
    UC-->>API: S1000DProceduralDataModule
    API->>Val: validate(module)
    Val-->>API: ProceduralValidationResults
    API->>Persist: persist(module)
    alt APPROVED
        Persist->>Repo: save_trusted(module)
    else NOT_REVIEWED
        Persist->>Repo: save_review(module)
    end
    API-->>Client: ProceduralProcessResponse
```

---

## Data Flow -- Batch Processing

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant Batch as BatchProcessingService
    participant UC as MappingUseCase
    participant Persist as PersistenceService

    Client->>API: POST /process/batch {items: [...]}
    API->>Batch: process_batch(items)
    loop For each item
        Batch->>UC: execute(item)
        alt Success
            Batch->>Persist: persist(module)
        else Error
            Note over Batch: Record error, continue
        end
    end
    Batch-->>API: BatchReport
    API-->>Client: BatchProcessResponse
```

### Async Batch (Bounded Concurrency)

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant AsyncBatch as AsyncBatchProcessingService
    participant Semaphore as asyncio.Semaphore(N)
    participant UC as MappingUseCase

    Client->>API: POST /process/batch {items: [...]}
    API->>AsyncBatch: process_batch(items)
    par Concurrent (max N)
        AsyncBatch->>Semaphore: acquire()
        AsyncBatch->>UC: asyncio.to_thread(execute, item1)
        AsyncBatch->>Semaphore: release()
    and
        AsyncBatch->>Semaphore: acquire()
        AsyncBatch->>UC: asyncio.to_thread(execute, item2)
        AsyncBatch->>Semaphore: release()
    and
        Note over AsyncBatch: ... up to N concurrent
    end
    AsyncBatch-->>API: BatchReport
    API-->>Client: BatchProcessResponse
```

---

## Cross-Cutting Concerns

### Observability Architecture

```mermaid
flowchart LR
    subgraph "Instrumented Wrappers (Decorator Pattern)"
        A[InstrumentedFaultMappingUseCase]
        B[InstrumentedFaultModulePersistenceService]
        C[InstrumentedFaultModuleReviewService]
        D[InstrumentedFaultModuleReconciliationService]
        E[InstrumentedFaultBatchProcessingService]
        F[InstrumentedProceduralMappingUseCase]
        G[InstrumentedProceduralPersistenceService]
        H[InstrumentedProceduralBatchProcessingService]
    end

    subgraph "MetricsSinkPort"
        M[increment / timing / gauge]
    end

    A --> M
    B --> M
    C --> M
    D --> M
    E --> M
    F --> M
    G --> M
    H --> M

    M --> I[(InMemoryMetricsSink)]
    M --> J[(Prometheus / Datadog / Custom)]
```

### Dependency Injection (Composition Roots)

```mermaid
flowchart TB
    subgraph "FaultMapperFactory"
        FC[AppConfig] --> FW[Wire fault adapters]
        FW --> FUC[FaultMappingUseCase]
        FW --> FPS[FaultModulePersistenceService]
        FW --> FRS[FaultModuleReviewService]
        FW --> FRCS[FaultModuleReconciliationService]
        FW --> FBS[FaultBatchProcessingService]
    end

    subgraph "ProceduralMapperFactory"
        PC[ProceduralAppConfig] --> PW[Wire procedural adapters]
        PW --> PUC[ProceduralMappingUseCase]
        PW --> PPS[ProceduralModulePersistenceService]
        PW --> PBS[ProceduralBatchProcessingService]
    end
```

---

## Architecture Decision Records

### ADR-1: Hexagonal Architecture

**Decision:** Use hexagonal (ports-and-adapters) architecture.

**Rationale:** The system must support multiple deployment modes (HTTP API, CLI), multiple persistence backends (in-memory, MongoDB), and multiple LLM providers. Hexagonal architecture enables this flexibility while keeping the domain logic pure and testable.

### ADR-2: Two-Pass Strategy (RULE then LLM)

**Decision:** Always attempt deterministic rule-based interpretation before falling back to LLM.

**Rationale:** LLM calls are expensive (latency + cost) and non-deterministic. Rules provide fast, free, reproducible results for well-structured inputs. LLM is the semantic fallback for ambiguous or novel content.

### ADR-3: typing.Protocol over ABC

**Decision:** Use `typing.Protocol` for all port interfaces instead of `abc.ABC`.

**Rationale:** Structural subtyping (duck typing) allows any adapter to satisfy a port without explicit inheritance. This reduces coupling and makes testing with fakes trivial.

### ADR-4: Frozen Dataclasses for Domain Objects

**Decision:** All domain models, value objects, and configuration are frozen (immutable) dataclasses.

**Rationale:** Immutability prevents accidental mutation bugs, makes objects hashable, and clarifies the data flow (new objects are created, old ones are never modified).

### ADR-5: Per-Item Error Isolation in Batch Processing

**Decision:** Batch processing catches per-item errors and continues, never aborting the entire batch.

**Rationale:** In production, a single malformed document should not prevent processing of the remaining batch. The `BatchReport` captures both successes and failures for downstream handling.

### ADR-6: Async via asyncio.to_thread()

**Decision:** Use cases remain synchronous; async services wrap them with `asyncio.to_thread()`.

**Rationale:** The mapping logic is CPU-bound (no I/O in the use case itself). Running it in a thread pool keeps the event loop free for I/O-bound operations (repository, audit, metrics) while avoiding the complexity of making every internal component async.

---

## File Counts Summary

| Layer | Files | Purpose |
|---|---|---|
| Domain | 8 | Models, enums, ports, value objects |
| Application | 32 | Use cases, services (sync + async) |
| Primary Adapters | 9 | HTTP API (7) + CLI (2) |
| Secondary Adapters | 21 | LLM, rules, repos, validators, serializers, metrics |
| Infrastructure | 4 | Factories, configuration |
| Schemas | 1 | JSON Schema |
| **Source Total** | **84** | |
| Tests | 70 | Unit (35) + API (2) + CLI (2) + Integration (4) + Fakes (9) + Fixtures (4) + conftest (1) + helpers |
| **Grand Total** | **154** | |
