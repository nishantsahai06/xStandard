"""HTTP routes — thin async handlers that delegate to application services.

Every handler:
  1. Validates the request via Pydantic DTOs (automatic in FastAPI).
  2. Converts DTOs → domain types where needed.
  3. Calls the appropriate (async) application service.
  4. Converts the service result → response DTO.
  5. Returns a JSON response with the correct status code.

No business logic lives here.

Supports both ``ServiceProvider`` (sync) and ``AsyncServiceProvider``
(async).  When an ``AsyncServiceProvider`` is injected, handlers
``await`` the async service methods directly.  When a sync
``ServiceProvider`` is injected, handlers call sync methods wrapped
in ``asyncio.to_thread`` so the event loop stays unblocked.
"""

from __future__ import annotations

import asyncio
from typing import Any, Union

from fastapi import APIRouter, HTTPException, Query

from fault_mapper.adapters.primary.api.dtos import (
    BatchItemResponse,
    BatchProcessRequest,
    BatchProcessResponse,
    ErrorResponse,
    HealthResponse,
    OrphansResponse,
    ProcessRequest,
    ProcessResponse,
    ReconciliationDetailResponse,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewItemResponse,
    ReviewListResponse,
    SweepRequest,
    SweepResponse,
)
from fault_mapper.adapters.primary.api.dependencies import (
    AsyncServiceProvider,
    ServiceProvider,
)
from fault_mapper.domain.models import (
    Chunk,
    DocumentPipelineOutput,
    ImageAsset,
    Metadata,
    Section,
    TableAsset,
)

# ── Module-level service holder ──────────────────────────────────────
# Set by ``create_app()`` before any request is served.
_services: Union[ServiceProvider, AsyncServiceProvider, None] = None
_is_async: bool = False


def set_services(services: Union[ServiceProvider, AsyncServiceProvider]) -> None:
    """Inject the wired service provider into the route module."""
    global _services, _is_async  # noqa: PLW0603
    _services = services
    _is_async = isinstance(services, AsyncServiceProvider)


def _svc() -> Union[ServiceProvider, AsyncServiceProvider]:
    """Return the current provider or fail fast."""
    if _services is None:
        raise RuntimeError("ServiceProvider not initialised")
    return _services


# ═══════════════════════════════════════════════════════════════════════
#  ROUTERS
# ═══════════════════════════════════════════════════════════════════════

health_router = APIRouter(tags=["health"])
process_router = APIRouter(tags=["process"])
review_router = APIRouter(prefix="/review", tags=["review"])
reconciliation_router = APIRouter(
    prefix="/reconciliation", tags=["reconciliation"],
)


# ═══════════════════════════════════════════════════════════════════════
#  HEALTH
# ═══════════════════════════════════════════════════════════════════════


@health_router.get(
    "/health",
    response_model=HealthResponse,
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS  (map → validate → persist)
# ═══════════════════════════════════════════════════════════════════════


def _to_domain_section(s: dict[str, Any]) -> Section:
    """Convert a raw section dict into a domain ``Section``."""
    chunks = [
        Chunk(
            chunk_text=c.get("chunk_text", ""),
            original_text=c.get("original_text", ""),
            contextual_prefix=c.get("contextual_prefix", ""),
            metadata=c.get("metadata", {}),
            id=c.get("id"),
        )
        for c in (s.get("chunks") or [])
    ]
    images = [
        ImageAsset(
            caption=im.get("caption"),
            page_number=im.get("page_number"),
            figure_label=im.get("figure_label"),
            id=im.get("id"),
        )
        for im in (s.get("images") or [])
    ]
    tables = [
        TableAsset(
            caption=tb.get("caption"),
            page_number=tb.get("page_number"),
            headers=tb.get("headers", []),
            rows=tb.get("rows", []),
            markdown_summary=tb.get("markdown_summary"),
            id=tb.get("id"),
        )
        for tb in (s.get("tables") or [])
    ]
    return Section(
        section_title=s.get("section_title", ""),
        section_order=s.get("section_order", 0),
        section_type=s.get("section_type", "general"),
        section_text=s.get("section_text", ""),
        level=s.get("level", 1),
        page_numbers=s.get("page_numbers", []),
        chunks=chunks,
        images=images,
        tables=tables,
        id=s.get("id"),
    )


def _request_to_pipeline_output(req: ProcessRequest) -> DocumentPipelineOutput:
    """Convert the Pydantic DTO to the domain ``DocumentPipelineOutput``."""
    sections = [
        _to_domain_section(s.model_dump()) for s in req.sections
    ]
    return DocumentPipelineOutput(
        id=req.id,
        full_text=req.full_text,
        file_name=req.file_name,
        file_type=req.file_type,
        source_path=req.source_path,
        metadata=Metadata(
            upload_metadata=req.metadata.upload_metadata,
            extraction_metadata=req.metadata.extraction_metadata,
        ),
        sections=sections,
        schematics=[],
    )


@process_router.post(
    "/process",
    response_model=ProcessResponse,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def process(body: ProcessRequest) -> ProcessResponse:
    """Map, validate, and persist a ``DocumentPipelineOutput``."""
    svc = _svc()

    if svc.use_case is None:
        raise HTTPException(
            status_code=503,
            detail="Mapping use case unavailable (no LLM client configured)",
        )

    # ── Map + validate ───────────────────────────────────────────
    source = _request_to_pipeline_output(body)
    try:
        # Use case is always sync (CPU-bound)
        module = await asyncio.to_thread(svc.use_case.execute, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Mapping failed: {exc}",
        ) from exc

    # ── Persist ──────────────────────────────────────────────────
    if _is_async:
        result = await svc.persistence.persist(module)
    else:
        result = svc.persistence.persist(module)

    return ProcessResponse(
        record_id=module.record_id,
        validation_status=module.validation_status.value,
        review_status=module.review_status.value,
        persisted=result.success,
        collection=result.collection or None,
        persistence_error=result.error,
        mode=module.mode.value if module.mode else None,
        mapping_version=module.mapping_version,
    )


# ═══════════════════════════════════════════════════════════════════════
#  BATCH PROCESS  (map → validate → persist — multiple items)
# ═══════════════════════════════════════════════════════════════════════


@process_router.post(
    "/process/batch",
    response_model=BatchProcessResponse,
    responses={
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def process_batch(body: BatchProcessRequest) -> BatchProcessResponse:
    """Map, validate, and persist multiple ``DocumentPipelineOutput`` items."""
    svc = _svc()

    if svc.batch is None:
        raise HTTPException(
            status_code=503,
            detail="Batch processing unavailable (no LLM client configured)",
        )

    # Convert DTOs → domain types
    sources = [_request_to_pipeline_output(item) for item in body.items]

    # Dispatch — async or sync
    if _is_async:
        report = await svc.batch.process_batch(sources)
    else:
        report = await asyncio.to_thread(svc.batch.process_batch, sources)

    return BatchProcessResponse(
        total=report.total,
        succeeded=report.succeeded,
        failed=report.failed,
        persisted_trusted=report.persisted_trusted,
        persisted_review=report.persisted_review,
        not_persisted=report.not_persisted,
        elapsed_ms=report.elapsed_ms,
        items=[
            BatchItemResponse(
                source_id=r.source_id,
                success=r.success,
                record_id=r.record_id,
                validation_status=r.validation_status,
                review_status=r.review_status,
                collection=r.collection,
                persisted=r.persisted,
                error=r.error,
                mode=r.mode,
                mapping_version=r.mapping_version,
            )
            for r in report.items
        ],
    )


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW WORKFLOW
# ═══════════════════════════════════════════════════════════════════════


@review_router.post(
    "/{record_id}/approve",
    response_model=ReviewActionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def approve(
    record_id: str,
    body: ReviewActionRequest | None = None,
) -> ReviewActionResponse:
    """Approve a review-queue item."""
    svc = _svc()
    req = body or ReviewActionRequest()
    if _is_async:
        result = await svc.review.approve(
            record_id,
            reason=req.reason,
            performed_by=req.performed_by,
        )
    else:
        result = svc.review.approve(
            record_id,
            reason=req.reason,
            performed_by=req.performed_by,
        )
    if not result.success and "not found" in (result.error or "").lower():
        raise HTTPException(status_code=404, detail=result.error)
    return ReviewActionResponse(
        success=result.success,
        record_id=result.record_id,
        collection=result.collection,
        error=result.error,
    )


@review_router.post(
    "/{record_id}/reject",
    response_model=ReviewActionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def reject(
    record_id: str,
    body: ReviewActionRequest | None = None,
) -> ReviewActionResponse:
    """Reject a review-queue item."""
    svc = _svc()
    req = body or ReviewActionRequest()
    if _is_async:
        result = await svc.review.reject(
            record_id,
            req.reason,
            performed_by=req.performed_by,
        )
    else:
        result = svc.review.reject(
            record_id,
            req.reason,
            performed_by=req.performed_by,
        )
    if not result.success and "not found" in (result.error or "").lower():
        raise HTTPException(status_code=404, detail=result.error)
    return ReviewActionResponse(
        success=result.success,
        record_id=result.record_id,
        collection=result.collection,
        error=result.error,
    )


@review_router.get(
    "/{record_id}",
    response_model=ReviewItemResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_review_item(record_id: str) -> ReviewItemResponse:
    """Fetch a single review-queue item."""
    svc = _svc()
    if _is_async:
        env = await svc.review.get_review_item(record_id)
    else:
        env = svc.review.get_review_item(record_id)
    if env is None:
        raise HTTPException(
            status_code=404,
            detail=f"Review item {record_id!r} not found",
        )
    return ReviewItemResponse(
        record_id=env.record_id,
        collection=env.collection,
        validation_status=env.validation_status.value,
        review_status=env.review_status.value,
        mapping_version=env.mapping_version,
        stored_at=env.stored_at,
    )


@review_router.get(
    "",
    response_model=ReviewListResponse,
)
async def list_review_items(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ReviewListResponse:
    """List items in the review queue."""
    svc = _svc()
    if _is_async:
        items = await svc.review.list_review_items(limit=limit, offset=offset)
        count = await svc.review.count_review_items()
    else:
        items = svc.review.list_review_items(limit=limit, offset=offset)
        count = svc.review.count_review_items()
    return ReviewListResponse(
        items=[
            ReviewItemResponse(
                record_id=e.record_id,
                collection=e.collection,
                validation_status=e.validation_status.value,
                review_status=e.review_status.value,
                mapping_version=e.mapping_version,
                stored_at=e.stored_at,
            )
            for e in items
        ],
        count=count,
    )


# ═══════════════════════════════════════════════════════════════════════
#  RECONCILIATION
# ═══════════════════════════════════════════════════════════════════════


@reconciliation_router.post(
    "/sweep",
    response_model=SweepResponse,
)
async def sweep(body: SweepRequest | None = None) -> SweepResponse:
    """Run a reconciliation sweep."""
    svc = _svc()
    req = body or SweepRequest()
    if _is_async:
        report = await svc.reconciliation.sweep(
            dry_run=req.dry_run,
            limit=req.limit,
        )
    else:
        report = svc.reconciliation.sweep(
            dry_run=req.dry_run,
            limit=req.limit,
        )
    return SweepResponse(
        total_review_scanned=report.total_review_scanned,
        duplicates_found=report.duplicates_found,
        duplicates_cleaned=report.duplicates_cleaned,
        duplicates_skipped=report.duplicates_skipped,
        errors=report.errors,
        dry_run=report.dry_run,
        details=[
            ReconciliationDetailResponse(
                record_id=d.record_id,
                outcome=d.outcome.value,
                reason=d.reason,
            )
            for d in report.details
        ],
    )


@reconciliation_router.get(
    "/orphans",
    response_model=OrphansResponse,
)
async def orphans() -> OrphansResponse:
    """List orphaned review IDs."""
    svc = _svc()
    if _is_async:
        ids = await svc.reconciliation.find_orphaned_review_ids()
    else:
        ids = svc.reconciliation.find_orphaned_review_ids()
    return OrphansResponse(orphan_ids=ids, count=len(ids))
