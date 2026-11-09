"""The FastAPI application: create_app() with lifespan and CORS, a health route, and include_router for every module in routers/. Tasks: 1.5, 4.1. The OpenAPI export command is in app/cli.py."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.core.body_limit import BodyLimitMiddleware
from app.core.db import create_engine, create_session_factory
from app.core.errors import ErrorResponse, register_error_handlers
from app.core.logging import configure_logging
from app.core.queue import ArqQueueClient
from app.core.request_id import RequestIdMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.sentry import init_sentry
from app.routers import account, account_profile, account_role, auth, files, notifier
from app.seeds.registry import seed_items
from app.seeds.runner import run_seeds

API_PREFIX = "/api/v1"

# The one list of feature routers: the include loop in create_app and the layout test read it.
ROUTERS = (account, account_profile, account_role, auth, files, notifier)

# One tag per feature router, in the order of the docs. Declared here so /docs lists
# every module even while its router has no route yet.
TAGS = [
    {"name": "account", "description": "The signed-in account."},
    {"name": "account_profile", "description": "Profile of an account."},
    {"name": "account_role", "description": "Roles of an account."},
    {"name": "auth", "description": "Sign-in, tokens and passwords."},
    {"name": "files", "description": "File upload and download."},
    {"name": "notifier", "description": "Notifications (no public route)."},
]

# Declared on the app so every route, including one added straight to `app`, documents the
# contract body for 422 and 500 and FastAPI's own HTTPValidationError is not advertised.
# WHY: `Any` is the value type of FastAPI's own `responses` parameter; the dict is passed through unchanged (POC-4.2).
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Validation failed"},
    500: {"model": ErrorResponse, "description": "Unexpected error"},
}

logger = logging.getLogger(__name__)

# The environments that serve /docs, /redoc and /openapi.json (task 11.6): the two a developer runs by hand.
CONTRACT_PAGE_ENVS = frozenset({"local", "development"})


class HealthResponse(BaseModel):
    status: Literal["ok"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The cache (9.x) is started before the yield and closed after it. The engine and the queue client are built in
    # create_app (neither opens a connection) and closed here.
    engine: AsyncEngine | None = app.state.engine
    queue: ArqQueueClient = app.state.queue
    logger.info("application startup")
    try:
        session_factory = app.state.session_factory
        if session_factory is not None:
            # A failed seed stops the boot (rule D5, approved in POC-5.1): the Node base logged it and served on,
            # which left an app with no roles that looked healthy. Without DATABASE_URL there is nothing to seed.
            await run_seeds(session_factory, seed_items(app.state.settings))
        yield
    finally:
        await queue.close()
        if engine is not None:
            await engine.dispose()
        logger.info("application shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    init_sentry(settings)
    # The Swagger UI, ReDoc and /openapi.json are served for local work only. `app.openapi()` does not need the served
    # route, so `python -m app.cli --export-openapi` works in every environment (POC-11.6, ADR-0033).
    serves_contract = settings.app_env in CONTRACT_PAGE_ENVS
    app = FastAPI(
        title="poc-base-fast-api",
        lifespan=lifespan,
        openapi_tags=TAGS,
        responses=ERROR_RESPONSES,
        docs_url="/docs" if serves_contract else None,
        redoc_url="/redoc" if serves_contract else None,
        openapi_url="/openapi.json" if serves_contract else None,
    )
    # Read by the auth dependencies (app/dependencies.py), so they see what the app booted with.
    app.state.settings = settings
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine) if engine else None
    # Task 6.1: the Redis pool opens on the first enqueue, so the app boots with no Redis.
    app.state.queue = ArqQueueClient(settings)
    # Added before CORS on purpose: the last middleware added is the outermost, and a 413
    # must still carry the CORS headers or a browser reports a CORS error instead.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    # The methods are the ones the Node base's enableCors allowed; "*" headers are echoed
    # on a preflight, which is how Authorization and x-refresh-token (ADR-0008) get through.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "HEAD", "PUT", "PATCH", "POST", "DELETE"],
        allow_headers=["*"],
    )
    # Outside CORS and the body limit, so the 413 and a CORS preflight carry the headers too; the request id is added
    # after it and sits outside it. Starlette's own error middleware is still outside all of ours.
    app.add_middleware(SecurityHeadersMiddleware)
    # The outermost of our middleware: the id is set before anything of ours runs, so a 413 and a preflight carry it.
    # Starlette's error middleware is outside it, which is why an unhandled 500 gets its id from the scope instead
    # (app/core/errors.py).
    app.add_middleware(RequestIdMiddleware)

    register_error_handlers(app, expose_trace=settings.app_env == "local")

    api = APIRouter(prefix=API_PREFIX)

    @api.get("/health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    for module in ROUTERS:
        api.include_router(module.router)

    app.include_router(api)
    return app


def run() -> None:
    """Console script `poc-base-fast-api` (ADR-0012): serve create_app() on PORT."""
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        # log_config=None keeps uvicorn's own handlers off, so its lines use our JSON format.
        log_config=None,
        # uvicorn handles SIGTERM itself; the timeout bounds how long in-flight requests get.
        timeout_graceful_shutdown=settings.shutdown_timeout_seconds,
    )
