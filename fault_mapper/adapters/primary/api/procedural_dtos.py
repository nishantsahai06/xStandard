"""Procedural-specific request / response DTOs for the HTTP API.

Reuses ``ProcessRequest`` (same ``DocumentPipelineOutput`` shape) from
the shared DTOs.  Only the response DTO differs because procedural
modules have ``module_type`` instead of ``mode``, and route on
``review_status`` instead of ``validation_status``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProceduralProcessResponse(BaseModel):
    """Output DTO for ``POST /procedural/process``."""

    record_id: str
    module_type: str
    review_status: str
    persisted: bool
    collection: str | None = None
    persistence_error: str | None = None
    mapping_version: str | None = None


class ProceduralReviewItemResponse(BaseModel):
    """Single procedural review-queue item."""

    record_id: str
    collection: str
    review_status: str
    mapping_version: str | None = None
    stored_at: str | None = None


class ProceduralReviewListResponse(BaseModel):
    """Paginated list of procedural review items."""

    items: list[ProceduralReviewItemResponse]
    count: int


# ═══════════════════════════════════════════════════════════════════════
#  BATCH
# ═══════════════════════════════════════════════════════════════════════


class ProceduralBatchProcessRequest(BaseModel):
    """Input DTO for ``POST /procedural/process/batch``."""

    items: list[object] = Field(
        ..., min_length=1, description="List of documents to process.",
    )


class ProceduralBatchItemResponse(BaseModel):
    """Per-item result within a procedural batch response."""

    source_id: str
    success: bool
    record_id: str | None = None
    review_status: str | None = None
    collection: str | None = None
    persisted: bool = False
    error: str | None = None
    module_type: str | None = None
    mapping_version: str | None = None


class ProceduralBatchProcessResponse(BaseModel):
    """Output DTO for ``POST /procedural/process/batch``."""

    total: int
    succeeded: int
    failed: int
    persisted_trusted: int
    persisted_review: int
    not_persisted: int
    elapsed_ms: float
    items: list[ProceduralBatchItemResponse]
