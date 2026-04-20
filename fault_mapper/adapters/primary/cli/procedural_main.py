"""Typer CLI entry point for the procedural-module pipeline.

Delegates to the same application services as the HTTP API.

Usage:

    python -m fault_mapper.adapters.primary.cli.procedural_main --help
    python -m fault_mapper.adapters.primary.cli.procedural_main process-procedural input.json

Or, when registered on the shared CLI:

    fault-mapper process-procedural input.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Union

import typer

from fault_mapper.adapters.primary.api.procedural_dependencies import (
    ProceduralServiceProvider,
)
from fault_mapper.domain.models import (
    Chunk,
    DocumentPipelineOutput,
    Metadata,
    Section,
)

procedural_cli = typer.Typer(
    name="procedural",
    help="Procedural-module pipeline CLI.",
    no_args_is_help=True,
)

# ── Module-level service holder (overridden in tests) ────────────────
_services: ProceduralServiceProvider | None = None


def set_procedural_services(services: ProceduralServiceProvider | None) -> None:
    """Inject a pre-built ``ProceduralServiceProvider`` (for testing)."""
    global _services  # noqa: PLW0603
    _services = services


def _svc() -> ProceduralServiceProvider:
    """Return the current provider or fail fast."""
    if _services is None:
        raise RuntimeError(
            "ProceduralServiceProvider not initialised.  "
            "Call set_procedural_services() first."
        )
    return _services


def _out(data: dict) -> None:
    """Print compact JSON to stdout."""
    typer.echo(json.dumps(data, indent=2, default=str))


def _json_to_pipeline_output(data: dict) -> DocumentPipelineOutput:
    """Convert a raw JSON dict to ``DocumentPipelineOutput``."""
    sections: list[Section] = []
    for s in data.get("sections", []):
        chunks = [
            Chunk(
                chunk_text=c.get("chunk_text", ""),
                original_text=c.get("original_text", ""),
                contextual_prefix=c.get("contextual_prefix", ""),
                metadata=c.get("metadata", {}),
                id=c.get("id"),
            )
            for c in s.get("chunks", [])
        ]
        sections.append(
            Section(
                section_title=s.get("section_title", ""),
                section_order=s.get("section_order", 0),
                section_type=s.get("section_type", "general"),
                section_text=s.get("section_text", ""),
                level=s.get("level", 1),
                page_numbers=s.get("page_numbers", []),
                chunks=chunks,
                id=s.get("id"),
            )
        )

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


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS PROCEDURAL
# ═══════════════════════════════════════════════════════════════════════


@procedural_cli.command("process-procedural")
def process_procedural(
    path: Path = typer.Argument(
        ..., help="Path to a JSON file containing DocumentPipelineOutput.",
    ),
) -> None:
    """Map, validate, and persist a procedural DocumentPipelineOutput JSON file."""
    svc = _svc()

    if svc.use_case is None:
        typer.echo(
            json.dumps({"error": "Procedural mapping use case unavailable (no LLM)"}),
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Load input ───────────────────────────────────────────────
    if not path.exists():
        typer.echo(
            json.dumps({"error": f"File not found: {path}"}),
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        typer.echo(
            json.dumps({"error": f"Invalid input: {exc}"}),
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Validate minimal shape ───────────────────────────────────
    if "id" not in raw:
        typer.echo(
            json.dumps({"error": "Input JSON missing required field 'id'"}),
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Map + validate ───────────────────────────────────────────
    try:
        source = _json_to_pipeline_output(raw)
        module = svc.use_case.execute(source)
    except ValueError as exc:
        typer.echo(json.dumps({"error": str(exc)}), err=True)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.echo(
            json.dumps({"error": f"Procedural mapping failed: {exc}"}),
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Persist ──────────────────────────────────────────────────
    result = svc.persistence.persist(module)

    _out({
        "record_id": module.record_id,
        "module_type": module.module_type.value,
        "review_status": module.review_status.value,
        "persisted": result.success,
        "collection": result.collection or None,
        "persistence_error": result.error,
        "mapping_version": module.mapping_version,
    })

    if not result.success:
        raise typer.Exit(code=1)


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS PROCEDURAL BATCH
# ═══════════════════════════════════════════════════════════════════════


@procedural_cli.command("process-procedural-batch")
def process_procedural_batch(
    path: Path = typer.Argument(
        ..., help="Path to a JSON file containing an array of DocumentPipelineOutput items.",
    ),
) -> None:
    """Map, validate, and persist a batch of procedural DocumentPipelineOutput items."""
    svc = _svc()

    if svc.use_case is None:
        typer.echo(
            json.dumps({"error": "Procedural mapping use case unavailable (no LLM)"}),
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Load input ───────────────────────────────────────────────
    if not path.exists():
        typer.echo(
            json.dumps({"error": f"File not found: {path}"}),
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        typer.echo(
            json.dumps({"error": f"Invalid input: {exc}"}),
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Validate shape: must be a list ───────────────────────────
    if not isinstance(raw, list):
        typer.echo(
            json.dumps({"error": "Input JSON must be an array of documents"}),
            err=True,
        )
        raise typer.Exit(code=1)

    if len(raw) == 0:
        typer.echo(
            json.dumps({"error": "Input array is empty"}),
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Convert items ────────────────────────────────────────────
    sources = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "id" not in item:
            typer.echo(
                json.dumps({"error": f"Item {i} missing required field 'id'"}),
                err=True,
            )
            raise typer.Exit(code=1)
        sources.append(_json_to_pipeline_output(item))

    # ── Run batch ────────────────────────────────────────────────
    if getattr(svc, "batch", None) is not None:
        report = svc.batch.process_batch(sources)
    else:
        # Fallback: construct an ad-hoc batch service
        from fault_mapper.application.procedural_batch_processing_service import (
            ProceduralBatchProcessingService,
        )
        batch_svc = ProceduralBatchProcessingService(
            use_case=svc.use_case,
            persistence=svc.persistence,
        )
        report = batch_svc.process_batch(sources)

    _out({
        "total": report.total,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "persisted_trusted": report.persisted_trusted,
        "persisted_review": report.persisted_review,
        "not_persisted": report.not_persisted,
        "elapsed_ms": report.elapsed_ms,
        "items": [
            {
                "source_id": r.source_id,
                "success": r.success,
                "record_id": r.record_id,
                "review_status": r.review_status,
                "collection": r.collection,
                "persisted": r.persisted,
                "error": r.error,
                "module_type": r.mode,
                "mapping_version": r.mapping_version,
            }
            for r in report.items
        ],
    })

    if report.failed > 0:
        raise typer.Exit(code=1)


# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for ``python -m …``."""
    procedural_cli()


if __name__ == "__main__":
    main()
