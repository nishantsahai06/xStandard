"""Shared DTO-to-domain conversion helpers for primary adapters.

Centralises the conversion from raw dicts / Pydantic DTOs to
domain ``DocumentPipelineOutput`` so that CLI and API adapters
share a single implementation.
"""

from __future__ import annotations

from typing import Any

from fault_mapper.domain.models import (
    Chunk,
    DocumentPipelineOutput,
    ImageAsset,
    Metadata,
    Section,
    TableAsset,
)


def dict_to_section(s: dict[str, Any]) -> Section:
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


def json_to_pipeline_output(data: dict[str, Any]) -> DocumentPipelineOutput:
    """Convert a raw JSON dict to ``DocumentPipelineOutput``.

    Used by both the CLI and API adapters to avoid duplicating
    the conversion logic.
    """
    sections = [dict_to_section(s) for s in data.get("sections", [])]

    raw_meta = data.get("metadata", {})
    return DocumentPipelineOutput(
        id=data["id"],
        full_text=data.get("full_text", ""),
        file_name=data.get("file_name", "unknown"),
        file_type=data.get("file_type", "pdf"),
        source_path=data.get("source_path", ""),
        metadata=Metadata(
            upload_metadata=raw_meta.get("upload_metadata", {}),
            extraction_metadata=raw_meta.get("extraction_metadata", {}),
        ),
        sections=sections,
        schematics=[],
    )
