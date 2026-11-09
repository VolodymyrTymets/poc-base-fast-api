"""The request id on responses and log lines of the real app. Task: POC-11.6 (ADR-0033). No database: the lifespan is not run."""

import asyncio
import io
import json
import logging
import re
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from utils.client import client_for

from app.config import DEFAULT_CORS_ORIGINS, Settings
from app.core.logging import JsonFormatter
from app.main import create_app

HEADER = "x-request-id"
GENERATED = re.compile(r"[0-9a-f]{32}")
ROUTE_LOGGER = "test.request_id.route"
ERRORS_LOGGER = "app.core.errors"


@pytest.fixture
def log_lines() -> Iterator[io.StringIO]:
    """Our JSON formatter on a private stream, so the ids are written the way production writes them."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    names = (ROUTE_LOGGER, ERRORS_LOGGER)
    loggers = [logging.getLogger(name) for name in names]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    yield stream
    for logger in loggers:
        logger.removeHandler(handler)


def entries(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def make_app() -> FastAPI:
    settings = Settings(
        cors_origins=list(DEFAULT_CORS_ORIGINS), max_request_body_bytes=1024
    )
    app = create_app(settings)
    route_logger = logging.getLogger(ROUTE_LOGGER)
    barrier = asyncio.Barrier(2)

    @app.get("/api/v1/_log")
    async def log() -> dict[str, str]:
        route_logger.info("inside the route")
        return {"ok": "yes"}

    @app.get("/api/v1/_log_together")
    async def log_together() -> dict[str, str]:
        # Both requests are inside the handler at once before either logs.
        await barrier.wait()
        route_logger.info("after the barrier")
        return {"ok": "yes"}

    @app.post("/api/v1/_body")
    async def body(payload: dict[str, str]) -> dict[str, int]:
        return {"size": len(payload)}

    @app.get("/api/v1/_boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    return app


async def test_a_well_formed_id_is_echoed() -> None:
    # Arrange
    async with client_for(make_app()) as client:
        # Act
        response = await client.get("/api/v1/health", headers={HEADER: "abc-123"})

    # Assert
    assert response.headers[HEADER] == "abc-123"


async def test_a_missing_id_is_generated() -> None:
    # Arrange
    async with client_for(make_app()) as client:
        # Act
        response = await client.get("/api/v1/health")

    # Assert
    assert GENERATED.fullmatch(response.headers[HEADER])


async def test_a_malformed_id_is_replaced_and_never_logged(
    log_lines: io.StringIO,
) -> None:
    # Arrange
    bad = "bad id with spaces"
    async with client_for(make_app()) as client:
        # Act
        response = await client.get("/api/v1/_log", headers={HEADER: bad})

    # Assert
    assert GENERATED.fullmatch(response.headers[HEADER])
    assert bad not in log_lines.getvalue()


async def test_a_log_line_written_in_the_route_carries_the_response_id(
    log_lines: io.StringIO,
) -> None:
    # Arrange
    async with client_for(make_app()) as client:
        # Act
        response = await client.get("/api/v1/_log", headers={HEADER: "abc-123"})

    # Assert
    assert [e["request_id"] for e in entries(log_lines)] == [response.headers[HEADER]]


async def test_a_log_line_outside_a_request_has_no_id(
    log_lines: io.StringIO,
) -> None:
    # Arrange
    route_logger = logging.getLogger(ROUTE_LOGGER)

    # Act
    route_logger.info("not in a request")

    # Assert
    assert "request_id" not in entries(log_lines)[0]


async def test_two_concurrent_requests_log_their_own_ids(
    log_lines: io.StringIO,
) -> None:
    # Arrange
    async with client_for(make_app()) as client:
        # Act
        await asyncio.gather(
            client.get("/api/v1/_log_together", headers={HEADER: "first-1"}),
            client.get("/api/v1/_log_together", headers={HEADER: "second-2"}),
        )

    # Assert
    assert sorted(str(e["request_id"]) for e in entries(log_lines)) == [
        "first-1",
        "second-2",
    ]


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [("GET", "/api/v1/nowhere", 404), ("POST", "/api/v1/_body", 413)],
    ids=["404", "413"],
)
async def test_a_404_and_a_413_carry_the_id(
    method: str, path: str, status: int
) -> None:
    # Arrange
    async with client_for(make_app()) as client:
        # Act
        response = await client.request(
            method, path, content=b"x" * 2048 if method == "POST" else None
        )

    # Assert
    assert (
        response.status_code,
        bool(GENERATED.fullmatch(response.headers[HEADER])),
    ) == (
        status,
        True,
    )


async def test_a_500_carries_the_id_in_the_header_and_in_the_error_log(
    log_lines: io.StringIO,
) -> None:
    # Arrange
    async with client_for(make_app(), raise_app_exceptions=False) as client:
        # Act
        response = await client.get("/api/v1/_boom", headers={HEADER: "abc-123"})

    # Assert
    logged = [e for e in entries(log_lines) if e["level"] == "ERROR"]
    assert (response.status_code, response.headers[HEADER]) == (500, "abc-123")
    assert [e["request_id"] for e in logged] == ["abc-123"]
