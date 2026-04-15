"""FastAPI application factory.

``create_app()`` builds a fully wired FastAPI instance.  The caller
provides a ``ServiceProvider`` (or parameters to build one).

    from fault_mapper.adapters.primary.api.app import create_app
    from fault_mapper.adapters.primary.api.dependencies import build_services

    services = build_services(llm_client=my_llm, repository=my_repo)
    app = create_app(services)

For development:

    uvicorn fault_mapper.adapters.primary.api.app:app --reload
"""

from __future__ import annotations

from typing import Union

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from fault_mapper.adapters.primary.api.dependencies import (
    AsyncServiceProvider,
    ServiceProvider,
    build_services,
)
from fault_mapper.adapters.primary.api.routes import (
    health_router,
    process_router,
    reconciliation_router,
    review_router,
    set_services,
)


def create_app(
    services: Union[ServiceProvider, AsyncServiceProvider, None] = None,
    *,
    title: str = "Fault Module Pipeline API",
    version: str = "0.1.0",
) -> FastAPI:
    """Build and return a configured FastAPI application.

    Parameters
    ----------
    services
        Pre-built service provider.  If None, ``build_services()``
        is called with defaults (in-memory repo, no LLM).
    title
        OpenAPI title.
    version
        OpenAPI version.
    """
    if services is None:
        services = build_services()

    set_services(services)

    application = FastAPI(title=title, version=version)

    # ── Register routers ─────────────────────────────────────────
    application.include_router(health_router)
    application.include_router(process_router)
    application.include_router(review_router)
    application.include_router(reconciliation_router)

    # ── Generic exception handler ────────────────────────────────
    @application.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc)},
        )

    return application


# ── Default instance for ``uvicorn … app:app`` ───────────────────────
app = create_app()
