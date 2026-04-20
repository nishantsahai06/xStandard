"""Typer CLI entry point for the fault-module pipeline.

Delegates to the same application services as the HTTP API.

Usage:

    python -m fault_mapper.adapters.primary.cli.main --help
    python -m fault_mapper.adapters.primary.cli.main health
    python -m fault_mapper.adapters.primary.cli.main process input.json
    python -m fault_mapper.adapters.primary.cli.main approve REC-001
    python -m fault_mapper.adapters.primary.cli.main reject REC-001 --reason "Bad"
    python -m fault_mapper.adapters.primary.cli.main sweep --dry-run
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional, Union

import typer

from fault_mapper.adapters.primary.api.dependencies import (
    AsyncServiceProvider,
    ServiceProvider,
    build_services,
)
from fault_mapper.adapters.primary._conversion_helpers import (
    json_to_pipeline_output as _json_to_pipeline_output,
)

cli = typer.Typer(
    name="fault-mapper",
    help="Fault-module pipeline CLI.",
    no_args_is_help=True,
)

# ── Module-level service holder (overridden in tests) ────────────────
_services: Union[ServiceProvider, AsyncServiceProvider, None] = None


def set_services(services: Union[ServiceProvider, AsyncServiceProvider]) -> None:
    """Inject a pre-built ``ServiceProvider`` (for testing)."""
    global _services  # noqa: PLW0603
    _services = services


def _svc() -> Union[ServiceProvider, AsyncServiceProvider]:
    """Return the current provider, building defaults if needed."""
    global _services  # noqa: PLW0603
    if _services is None:
        _services = build_services()
    return _services


def _is_async_svc() -> bool:
    return isinstance(_svc(), AsyncServiceProvider)


def _out(data: dict) -> None:
    """Print compact JSON to stdout."""
    typer.echo(json.dumps(data, indent=2, default=str))


# ═══════════════════════════════════════════════════════════════════════
#  HEALTH
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
def health() -> None:
    """Check service health."""
    _out({"status": "ok"})


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
def process(
    path: Path = typer.Argument(
        ..., help="Path to a JSON file containing DocumentPipelineOutput.",
    ),
) -> None:
    """Map, validate, and persist a DocumentPipelineOutput JSON file."""
    svc = _svc()

    if svc.use_case is None:
        typer.echo(
            json.dumps({"error": "Mapping use case unavailable (no LLM)"}),
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
            json.dumps({"error": f"Mapping failed: {exc}"}),
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Persist ──────────────────────────────────────────────────
    if _is_async_svc():
        result = asyncio.run(svc.persistence.persist(module))
    else:
        result = svc.persistence.persist(module)

    _out({
        "record_id": module.record_id,
        "validation_status": module.validation_status.value,
        "review_status": module.review_status.value,
        "persisted": result.success,
        "collection": result.collection or None,
        "persistence_error": result.error,
        "mode": module.mode.value if module.mode else None,
        "mapping_version": module.mapping_version,
    })

    if not result.success:
        raise typer.Exit(code=1)


# ═══════════════════════════════════════════════════════════════════════
#  BATCH PROCESS
# ═══════════════════════════════════════════════════════════════════════


@cli.command("process-batch")
def process_batch(
    path: Path = typer.Argument(
        ..., help="Path to a JSON file containing an array of DocumentPipelineOutput items.",
    ),
) -> None:
    """Map, validate, and persist a batch of DocumentPipelineOutput JSON items."""
    svc = _svc()

    if svc.use_case is None:
        typer.echo(
            json.dumps({"error": "Mapping use case unavailable (no LLM)"}),
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
        if _is_async_svc():
            report = asyncio.run(svc.batch.process_batch(sources))
        else:
            report = svc.batch.process_batch(sources)
    else:
        # Fallback: construct an ad-hoc batch service
        from fault_mapper.application.fault_batch_processing_service import (
            FaultBatchProcessingService,
        )
        from fault_mapper.application.fault_module_persistence_service import (
            FaultModulePersistenceService,
        )
        batch_svc = FaultBatchProcessingService(
            use_case=svc.use_case,
            persistence=svc.persistence
            if isinstance(svc.persistence, FaultModulePersistenceService)
            else svc.persistence,
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
                "validation_status": r.validation_status,
                "review_status": r.review_status,
                "collection": r.collection,
                "persisted": r.persisted,
                "error": r.error,
                "mode": r.mode,
                "mapping_version": r.mapping_version,
            }
            for r in report.items
        ],
    })

    if report.failed > 0:
        raise typer.Exit(code=1)


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW WORKFLOW
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
def approve(
    record_id: str = typer.Argument(..., help="Record ID to approve."),
    reason: str = typer.Option("", help="Approval reason."),
    performed_by: Optional[str] = typer.Option(None, help="Reviewer ID."),
) -> None:
    """Approve a review-queue item."""
    svc = _svc()
    if _is_async_svc():
        result = asyncio.run(svc.review.approve(
            record_id, reason=reason, performed_by=performed_by,
        ))
    else:
        result = svc.review.approve(
            record_id, reason=reason, performed_by=performed_by,
        )
    _out({
        "success": result.success,
        "record_id": result.record_id,
        "collection": result.collection,
        "error": result.error,
    })
    if not result.success:
        raise typer.Exit(code=1)


@cli.command()
def reject(
    record_id: str = typer.Argument(..., help="Record ID to reject."),
    reason: str = typer.Option("", help="Rejection reason."),
    performed_by: Optional[str] = typer.Option(None, help="Reviewer ID."),
) -> None:
    """Reject a review-queue item."""
    svc = _svc()
    if _is_async_svc():
        result = asyncio.run(svc.review.reject(
            record_id, reason, performed_by=performed_by,
        ))
    else:
        result = svc.review.reject(
            record_id, reason, performed_by=performed_by,
        )
    _out({
        "success": result.success,
        "record_id": result.record_id,
        "collection": result.collection,
        "error": result.error,
    })
    if not result.success:
        raise typer.Exit(code=1)


# ═══════════════════════════════════════════════════════════════════════
#  RECONCILIATION
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
def sweep(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview only."),
    limit: Optional[int] = typer.Option(None, help="Max records to process."),
) -> None:
    """Run a reconciliation sweep."""
    svc = _svc()
    if _is_async_svc():
        report = asyncio.run(svc.reconciliation.sweep(dry_run=dry_run, limit=limit))
    else:
        report = svc.reconciliation.sweep(dry_run=dry_run, limit=limit)
    _out({
        "total_review_scanned": report.total_review_scanned,
        "duplicates_found": report.duplicates_found,
        "duplicates_cleaned": report.duplicates_cleaned,
        "duplicates_skipped": report.duplicates_skipped,
        "errors": report.errors,
        "dry_run": report.dry_run,
        "details": [
            {
                "record_id": d.record_id,
                "outcome": d.outcome.value,
                "reason": d.reason,
            }
            for d in report.details
        ],
    })


# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for ``python -m …``."""
    cli()


if __name__ == "__main__":
    main()
