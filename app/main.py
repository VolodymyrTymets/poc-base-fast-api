"""The FastAPI application: create_app() with lifespan and CORS, a health route, and include_router for every module in routers/. Tasks: 1.5, 4.1. The OpenAPI export command is in app/cli.py."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.core.body_limit import BodyLimitMiddleware
from app.core.db import create_engine, create_session_factory
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.sentry import init_sentry
from app.routers import account, account_profile, account_role, auth, files, notifier

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

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The arq pool (6.1) and the cache (9.x) are started before the yield and closed after
    # it. The engine is built in create_app (it opens no connection) and closed here.
    engine: AsyncEngine | None = app.state.engine
    logger.info("application startup")
    try:
        yield
    finally:
        if engine is not None:
            await engine.dispose()
        logger.info("application shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    init_sentry(settings)
    app = FastAPI(title="poc-base-fast-api", lifespan=lifespan, openapi_tags=TAGS)
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine) if engine else None
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
        port=settings.port,
        # log_config=None keeps uvicorn's own handlers off, so its lines use our JSON format.
        log_config=None,
        # uvicorn handles SIGTERM itself; the timeout bounds how long in-flight requests get.
        timeout_graceful_shutdown=settings.shutdown_timeout_seconds,
    )
