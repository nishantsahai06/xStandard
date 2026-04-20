"""Procedural HTTP routes — thin async handlers for the procedural pipeline.

Mirrors ``routes.py`` structurally but with procedural-specific services
and response shapes.  Delegates to ``ProceduralServiceProvider``.

Endpoints:
  POST /procedural/process   — map → validate → persist
  GET  /procedural/review     — list procedural review items
  GET  /procedural/review/{record_id} — fetch single review item
"""

from __future__ import annotations

import asyncio
from typing import Any, Union

from fastapi import APIRouter, HTTPException, Query

from fault_mapper.adapters.primary.api.dtos import (
    ErrorResponse,
    ProcessRequest,
)
from fault_mapper.adapters.primary.api.procedural_dtos import (
    ProceduralBatchItemResponse,
    ProceduralBatchProcessResponse,
    ProceduralProcessResponse,
    ProceduralReviewItemResponse,
    ProceduralReviewListResponse,
)
from fault_mapper.adapters.primary.api.procedural_dependencies import (
    ProceduralServiceProvider,
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
_procedural_services: ProceduralServiceProvider | None = None


def set_procedural_services(services: ProceduralServiceProvider | None) -> None:
    """Inject the wired procedural service provider."""
    global _procedural_services  # noqa: PLW0603
    _procedural_services = services


def _svc() -> ProceduralServiceProvider:
    """Return the current provider or fail fast."""
    if _procedural_services is None:
        raise RuntimeError("ProceduralServiceProvider not initialised")
    return _procedural_services


# ═══════════════════════════════════════════════════════════════════════
#  ROUTER
# ═══════════════════════════════════════════════════════════════════════

procedural_router = APIRouter(prefix="/procedural", tags=["procedural"])


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS (reuse the same DTO → domain conversion)
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


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS  (map → validate → persist)
# ═══════════════════════════════════════════════════════════════════════


@procedural_router.post(
    "/process",
    response_model=ProceduralProcessResponse,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def process_procedural(body: ProcessRequest) -> ProceduralProcessResponse:
    """Map, validate, and persist a procedural ``DocumentPipelineOutput``."""
    svc = _svc()

    if svc.use_case is None:
        raise HTTPException(
            status_code=503,
            detail="Procedural mapping use case unavailable (no LLM client configured)",
        )

    # ── Map + validate ───────────────────────────────────────────
    source = _request_to_pipeline_output(body)
    try:
        module = await asyncio.to_thread(svc.use_case.execute, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Procedural mapping failed: {exc}",
        ) from exc

    # ── Persist ──────────────────────────────────────────────────
    result = svc.persistence.persist(module)

    return ProceduralProcessResponse(
        record_id=module.record_id,
        module_type=module.module_type.value,
        review_status=module.review_status.value,
        persisted=result.success,
        collection=result.collection or None,
        persistence_error=result.error,
        mapping_version=module.mapping_version,
    )


# ═══════════════════════════════════════════════════════════════════════
#  BATCH PROCESS  (map → validate → persist — multiple items)
# ═══════════════════════════════════════════════════════════════════════


@procedural_router.post(
    "/process/batch",
    response_model=ProceduralBatchProcessResponse,
    responses={
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def process_procedural_batch(
    body: dict,
) -> ProceduralBatchProcessResponse:
    """Map, validate, and persist multiple procedural documents."""
    svc = _svc()

    if svc.batch is None:
        raise HTTPException(
            status_code=503,
            detail="Procedural batch processing unavailable (no LLM client configured)",
        )

    raw_items = body.get("items", [])
    if not raw_items:
        raise HTTPException(status_code=422, detail="items list must not be empty")

    sources = []
    for item in raw_items:
        req = ProcessRequest(**item)
        sources.append(_request_to_pipeline_output(req))

    # Dispatch — async or sync
    _has_async = asyncio.iscoroutinefunction(getattr(svc.batch, "process_batch", None))
    if _has_async:
        report = await svc.batch.process_batch(sources)
    else:
        report = await asyncio.to_thread(svc.batch.process_batch, sources)

    return ProceduralBatchProcessResponse(
        total=report.total,
        succeeded=report.succeeded,
        failed=report.failed,
        persisted_trusted=report.persisted_trusted,
        persisted_review=report.persisted_review,
        not_persisted=report.not_persisted,
        elapsed_ms=report.elapsed_ms,
        items=[
            ProceduralBatchItemResponse(
                source_id=r.source_id,
                success=r.success,
                record_id=r.record_id,
                review_status=r.review_status,
                collection=r.collection,
                persisted=r.persisted,
                error=r.error,
                module_type=r.mode,
                mapping_version=r.mapping_version,
            )
            for r in report.items
        ],
    )


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW — READ-ONLY VIEWS
# ═══════════════════════════════════════════════════════════════════════


@procedural_router.get(
    "/review/{record_id}",
    response_model=ProceduralReviewItemResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_procedural_review_item(record_id: str) -> ProceduralReviewItemResponse:
    """Fetch a single procedural review-queue item."""
    svc = _svc()
    env = svc.persistence.retrieve(record_id, "procedural_review")
    if env is None:
        raise HTTPException(
            status_code=404,
            detail=f"Procedural review item {record_id!r} not found",
        )
    return ProceduralReviewItemResponse(
        record_id=env.record_id,
        collection=env.collection,
        review_status=env.review_status.value,
        mapping_version=env.mapping_version,
        stored_at=env.stored_at,
    )


@procedural_router.get(
    "/review",
    response_model=ProceduralReviewListResponse,
)
async def list_procedural_review_items(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ProceduralReviewListResponse:
    """List items in the procedural review queue."""
    svc = _svc()
    items = svc.persistence.list_modules(
        "procedural_review", limit=limit, offset=offset,
    )
    count = svc.persistence.count_modules("procedural_review")
    return ProceduralReviewListResponse(
        items=[
            ProceduralReviewItemResponse(
                record_id=e.record_id,
                collection=e.collection,
                review_status=e.review_status.value,
                mapping_version=e.mapping_version,
                stored_at=e.stored_at,
            )
            for e in items
        ],
        count=count,
    )
