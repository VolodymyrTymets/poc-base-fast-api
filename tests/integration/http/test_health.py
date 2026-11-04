from fastapi.testclient import TestClient

from app.config import DEFAULT_CORS_ORIGINS, Settings
from app.main import create_app

WEB_APP = "http://localhost:5173"
UNKNOWN = "http://evil.test"
ALLOW_ORIGIN = "access-control-allow-origin"


def make_client(origins: list[str] | None = None) -> TestClient:
    # cors_origins is passed explicitly so a developer's CORS_ORIGINS never leaks in.
    settings = Settings(cors_origins=origins or list(DEFAULT_CORS_ORIGINS))
    return TestClient(create_app(settings))


def preflight(client: TestClient, origin: str) -> tuple[int, str | None]:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    return response.status_code, response.headers.get(ALLOW_ORIGIN)


def test_health_answers_ok() -> None:
    response = make_client().get("/api/v1/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_preflight_from_the_web_app_origin_is_allowed() -> None:
    assert preflight(make_client(), WEB_APP) == (200, WEB_APP)


def test_preflight_from_an_unknown_origin_is_refused() -> None:
    assert preflight(make_client(), UNKNOWN) == (400, None)


def test_a_simple_request_from_an_unknown_origin_gets_no_allow_header() -> None:
    response = make_client().get("/api/v1/health", headers={"Origin": UNKNOWN})

    assert (response.status_code, response.headers.get(ALLOW_ORIGIN)) == (200, None)


def test_configured_origins_replace_the_defaults() -> None:
    client = make_client(["http://localhost:4000"])

    assert preflight(client, "http://localhost:4000") == (200, "http://localhost:4000")
    assert preflight(client, WEB_APP) == (400, None)
