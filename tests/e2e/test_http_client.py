"""The `client` fixture (task 3.2): the real app over HTTP, with its lifespan run around the test."""

import logging

import httpx
import pytest
from fastapi import FastAPI
from utils.client import running_client

LIFESPAN_LOGGER = "app.main"


async def test_health_answers_through_the_client_fixture(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})


async def test_the_lifespan_starts_before_the_call_and_stops_after_the_client_closes(
    asgi_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LIFESPAN_LOGGER)
    seen: list[list[str]] = []

    async with running_client(asgi_app) as client:
        await client.get("/api/v1/health")
        seen.append([record.getMessage() for record in caplog.records])
    after = [record.getMessage() for record in caplog.records]

    assert seen == [["application startup"]]
    assert after == ["application startup", "application shutdown"]
