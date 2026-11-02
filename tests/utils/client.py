"""The HTTP client the e2e tests use: httpx on the ASGI app, with the lifespan run around it."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI


def client_for(app: FastAPI, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    """A client calling `app` in process. It does not run the lifespan: see `running_client`."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@asynccontextmanager
async def running_client(
    app: FastAPI, *, raise_app_exceptions: bool = True
) -> AsyncIterator[httpx.AsyncClient]:
    """A client for `app` between its lifespan startup and shutdown.

    ASGITransport never sends the lifespan events, so without this the app's engine is never disposed.
    """
    async with (
        app.router.lifespan_context(app),
        client_for(app, raise_app_exceptions=raise_app_exceptions) as client,
    ):
        yield client
