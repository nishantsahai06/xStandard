"""Request / response DTOs for the HTTP API.

Pydantic models that define the JSON contract at the API boundary.
These are **primary adapter** concerns — they never leak into the
domain or application layers.  Handlers convert between DTOs and
domain types; the domain remains Pydantic-free.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS (map + validate + persist)
# ═══════════════════════════════════════════════════════════════════════


class MetadataInput(BaseModel):
    """Mirrors ``fault_mapper.domain.models.Metadata``."""

    upload_metadata: dict[str, Any] = Field(default_factory=dict)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)


class SectionInput(BaseModel):
    """Minimal section representation accepted by the process endpoint."""

    section_title: str
    section_order: int = 0
    section_type: str = "general"
    section_text: str = ""
    level: int = 1
    page_numbers: list[int] = Field(default_factory=list)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    id: str | None = None


class ProcessRequest(BaseModel):
    """Input DTO for ``POST /process``.

    Mirrors ``DocumentPipelineOutput`` — the already-normalised output
    of the upstream document-extraction pipeline.
    """

    id: str
    full_text: str
    file_name: str
    file_type: str = "pdf"
    source_path: str = ""
    metadata: MetadataInput = Field(default_factory=MetadataInput)
    sections: list[SectionInput] = Field(default_factory=list)
    schematics: list[dict[str, Any]] = Field(default_factory=list)


class ProcessResponse(BaseModel):
    """Output DTO for ``POST /process``."""

    record_id: str
    validation_status: str
    review_status: str
    persisted: bool
    collection: str | None = None
    persistence_error: str | None = None
    mode: str | None = None
    mapping_version: str | None = None


# ═══════════════════════════════════════════════════════════════════════
#  BATCH PROCESS (map + validate + persist — multiple items)
# ═══════════════════════════════════════════════════════════════════════


class BatchProcessRequest(BaseModel):
    """Input DTO for ``POST /process/batch``.

    A thin wrapper around a list of ``ProcessRequest`` items.
    """

    items: list[ProcessRequest] = Field(
        ..., min_length=1, description="List of documents to process.",
    )


class BatchItemResponse(BaseModel):
    """Per-item result within a batch response."""

    source_id: str
    success: bool
    record_id: str | None = None
    validation_status: str | None = None
    review_status: str | None = None
    collection: str | None = None
    persisted: bool = False
    error: str | None = None
    mode: str | None = None
    mapping_version: str | None = None


class BatchProcessResponse(BaseModel):
    """Output DTO for ``POST /process/batch``."""

    total: int
    succeeded: int
    failed: int
    persisted_trusted: int
    persisted_review: int
    not_persisted: int
    elapsed_ms: float
    items: list[BatchItemResponse]


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW WORKFLOW
# ═══════════════════════════════════════════════════════════════════════


class ReviewActionRequest(BaseModel):
    """Body for approve / reject endpoints."""

    reason: str = ""
    performed_by: str | None = None


class ReviewActionResponse(BaseModel):
    """Response for approve / reject endpoints."""

    success: bool
    record_id: str
    collection: str
    error: str | None = None


class ReviewItemResponse(BaseModel):
    """Single review-queue item."""

    record_id: str
    collection: str
    validation_status: str
    review_status: str
    mapping_version: str | None = None
    stored_at: str | None = None


class ReviewListResponse(BaseModel):
    """Paginated list of review items."""

    items: list[ReviewItemResponse]
    count: int


# ═══════════════════════════════════════════════════════════════════════
#  RECONCILIATION
# ═══════════════════════════════════════════════════════════════════════


class SweepRequest(BaseModel):
    """Body for ``POST /reconciliation/sweep``."""

    dry_run: bool = False
    limit: int | None = None


class ReconciliationDetailResponse(BaseModel):
    """One record's sweep outcome."""

    record_id: str
    outcome: str
    reason: str


class SweepResponse(BaseModel):
    """Response for ``POST /reconciliation/sweep``."""

    total_review_scanned: int
    duplicates_found: int
    duplicates_cleaned: int
    duplicates_skipped: int
    errors: int
    dry_run: bool
    details: list[ReconciliationDetailResponse]


class OrphansResponse(BaseModel):
    """Response for ``GET /reconciliation/orphans``."""

    orphan_ids: list[str]
    count: int


# ═══════════════════════════════════════════════════════════════════════
#  HEALTH
# ═══════════════════════════════════════════════════════════════════════


class HealthResponse(BaseModel):
    """Response for ``GET /health``."""

    status: str = "ok"


# ═══════════════════════════════════════════════════════════════════════
#  ERROR
# ═══════════════════════════════════════════════════════════════════════


class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx / 5xx."""

    error: str
    detail: str | None = None
