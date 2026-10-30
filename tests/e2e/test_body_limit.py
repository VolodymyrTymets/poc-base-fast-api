from collections.abc import Iterator

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from app.config import DEFAULT_CORS_ORIGINS, Settings
from app.core.body_limit import TOO_LARGE_BODY, BodyLimitMiddleware
from app.main import create_app

LIMIT = 1024
WEB_APP = "http://localhost:5173"


def make_app(handled: list[int]) -> FastAPI:
    settings = Settings(
        cors_origins=list(DEFAULT_CORS_ORIGINS), max_request_body_bytes=LIMIT
    )
    app = create_app(settings)

    # The app has no body-reading route yet, so the test adds one to its own instance.
    @app.post("/api/v1/_echo")
    async def echo(request: Request) -> dict[str, int]:
        size = len(await request.body())
        handled.append(size)
        return {"size": size}

    @app.post("/api/v1/_json")
    async def parsed(payload: dict[str, str]) -> dict[str, int]:
        handled.append(len(payload))
        return {"keys": len(payload)}

    return app


def chunks(total: int, step: int) -> Iterator[bytes]:
    for _ in range(total // step):
        yield b"x" * step


def test_a_body_over_the_declared_limit_is_413_and_never_reaches_the_handler() -> None:
    handled: list[int] = []

    response = TestClient(make_app(handled)).post(
        "/api/v1/_echo", content=b"x" * (LIMIT + 1)
    )

    assert (response.status_code, response.json()) == (413, TOO_LARGE_BODY)
    assert handled == []


def test_a_body_at_exactly_the_limit_is_accepted() -> None:
    handled: list[int] = []

    response = TestClient(make_app(handled)).post("/api/v1/_echo", content=b"x" * LIMIT)

    assert (response.status_code, response.json()) == (200, {"size": LIMIT})


def test_a_chunked_body_over_the_limit_is_413() -> None:
    handled: list[int] = []

    # A generator has no length, so httpx sends it chunked without Content-Length.
    response = TestClient(make_app(handled)).post(
        "/api/v1/_echo", content=chunks(LIMIT * 4, 256)
    )

    assert (response.status_code, response.json()) == (413, TOO_LARGE_BODY)
    assert handled == []


def test_a_chunked_body_is_413_when_fastapi_parses_it() -> None:
    handled: list[int] = []

    # FastAPI turns a read error into a 400; the limit must win before that.
    response = TestClient(make_app(handled)).post(
        "/api/v1/_json",
        content=chunks(LIMIT * 4, 256),
        headers={"Content-Type": "application/json"},
    )

    assert (response.status_code, response.json()) == (413, TOO_LARGE_BODY)
    assert handled == []


def test_the_413_carries_cors_headers_for_an_allowed_origin() -> None:
    response = TestClient(make_app([])).post(
        "/api/v1/_echo", content=b"x" * (LIMIT + 1), headers={"Origin": WEB_APP}
    )

    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == WEB_APP


async def test_the_app_gets_no_more_bytes_once_the_limit_is_crossed() -> None:
    delivered = 0
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        # A handler that keeps reading after the first disconnect it is given.
        for _ in range(3):
            seen.append((await receive())["type"])

    async def receive() -> Message:
        nonlocal delivered
        delivered += 1
        return {"type": "http.request", "body": b"x" * 600, "more_body": True}

    async def send(message: Message) -> None:
        return None

    await BodyLimitMiddleware(app, max_bytes=LIMIT)(
        {"type": "http", "headers": []}, receive, send
    )

    assert seen == ["http.request", "http.disconnect", "http.disconnect"]
    assert delivered == 2


async def test_a_response_that_already_started_is_not_followed_by_a_413() -> None:
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()
        await receive()
        await send({"type": "http.response.body", "body": b"partial"})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"x" * 600, "more_body": True}

    async def send(message: Message) -> None:
        sent.append(message)

    await BodyLimitMiddleware(app, max_bytes=LIMIT)(
        {"type": "http", "headers": []}, receive, send
    )

    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == 200


async def test_a_lying_content_length_is_still_stopped_while_streaming() -> None:
    reached: list[int] = []
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        # Behaves like a handler that reads the whole body, then answers.
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            total += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        reached.append(total)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    incoming = [
        {"type": "http.request", "body": b"x" * 600, "more_body": True},
        {"type": "http.request", "body": b"x" * 600, "more_body": False},
    ]

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "headers": [(b"content-length", b"10")],
    }

    await BodyLimitMiddleware(app, max_bytes=LIMIT)(scope, receive, send)

    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert statuses == [413]
    assert reached == [600]
