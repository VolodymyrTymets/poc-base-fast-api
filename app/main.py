"""The FastAPI application: create_app() with lifespan and CORS, a health route, and include_router for every module in routers/. Tasks: 1.5, 4.1."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import Settings, get_settings

API_PREFIX = "/api/v1"


class HealthResponse(BaseModel):
    status: Literal["ok"]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Nothing to open yet. The database engine (2.1), the arq pool (6.1) and the
    # cache (9.x) are started before the yield and closed after it.
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="poc-base-fast-api", lifespan=lifespan)
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

    app.include_router(api)
    return app


def run() -> None:
    """Console script `poc-base-fast-api` (ADR-0012): serve create_app() on PORT."""
    uvicorn.run("app.main:create_app", factory=True, port=get_settings().port)
