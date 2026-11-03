"""The FastAPI application: create_app() with lifespan and CORS, a health route, and include_router for every module in routers/. Tasks: 1.5, 4.1."""

import argparse
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.core.body_limit import BodyLimitMiddleware
from app.core.db import create_engine, create_session_factory
from app.core.logging import configure_logging
from app.core.openapi import is_current, render
from app.core.sentry import init_sentry
from app.routers import account, account_profile, account_role, auth, files, notifier

API_PREFIX = "/api/v1"
# The committed contract at the repo root (ADR-0003); generated, never hand-edited.
OPENAPI_PATH = Path(__file__).resolve().parent.parent / "openapi.json"

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

    api = APIRouter(prefix=API_PREFIX)

    @api.get("/health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    for module in (account, account_profile, account_role, auth, files, notifier):
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


def export_openapi(path: Path = OPENAPI_PATH, *, check: bool = False) -> int:
    """Write the OpenAPI contract to `path`, or with `check` only compare it. Returns the exit status."""
    app = create_app(Settings())
    if check:
        if is_current(app, path):
            return 0
        sys.stderr.write(
            f"{path.name} is stale: run `uv run python -m app.main --export-openapi`\n"
        )
        return 1
    path.write_text(render(app), encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export the OpenAPI contract.")
    parser.add_argument("--export-openapi", action="store_true", required=True)
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    parser.add_argument("--path", type=Path, default=OPENAPI_PATH)
    options = parser.parse_args()
    sys.exit(export_openapi(options.path, check=options.check))
