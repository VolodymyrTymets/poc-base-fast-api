"""The security headers on the responses of the real app. Task: POC-11.6 (ADR-0033). No database: the lifespan is not run."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from app.config import DEFAULT_CORS_ORIGINS, Settings
from app.core.security_headers import SECURITY_HEADERS
from app.main import create_app

EXPECTED = {name.lower(): value for name, value in SECURITY_HEADERS}
WEB_APP = "http://localhost:5173"


def make_client() -> TestClient:
    settings = Settings(
        cors_origins=list(DEFAULT_CORS_ORIGINS), max_request_body_bytes=1024
    )
    app: FastAPI = create_app(settings)

    @app.post("/api/v1/_body")
    async def body(payload: dict[str, str]) -> dict[str, int]:
        return {"size": len(payload)}

    @app.get("/api/v1/_boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def security_headers(response: Response) -> dict[str, str]:
    return {
        name: response.headers[name] for name in EXPECTED if name in response.headers
    }


def test_a_200_carries_the_headers() -> None:
    # Arrange
    client = make_client()

    # Act
    response = client.get("/api/v1/health")

    # Assert
    assert (response.status_code, security_headers(response)) == (200, EXPECTED)


def test_a_404_carries_the_headers() -> None:
    # Arrange
    client = make_client()

    # Act
    response = client.get("/api/v1/nowhere")

    # Assert
    assert (response.status_code, security_headers(response)) == (404, EXPECTED)


def test_a_422_carries_the_headers() -> None:
    # Arrange
    client = make_client()

    # Act
    response = client.post("/api/v1/_body", content=b"not json")

    # Assert
    assert (response.status_code, security_headers(response)) == (422, EXPECTED)


def test_a_413_carries_the_headers() -> None:
    # Arrange
    client = make_client()

    # Act
    response = client.post("/api/v1/_body", content=b"x" * 2048)

    # Assert
    assert (response.status_code, security_headers(response)) == (413, EXPECTED)


def test_a_cors_preflight_carries_the_headers() -> None:
    # Arrange
    client = make_client()

    # Act
    response = client.options(
        "/api/v1/health",
        headers={"Origin": WEB_APP, "Access-Control-Request-Method": "GET"},
    )

    # Assert
    assert (response.status_code, security_headers(response)) == (200, EXPECTED)


def test_a_500_from_an_unhandled_exception_carries_none_of_them() -> None:
    # Known limitation, as for CORS (docs/api/ERRORS.md): Starlette answers an unhandled exception in its outermost
    # middleware, outside ours. This test records it; if it ever changes, update the docs with it.
    # Arrange
    client = make_client()

    # Act
    response = client.get("/api/v1/_boom")

    # Assert
    assert (response.status_code, security_headers(response)) == (500, {})
