"""SecurityHeadersMiddleware on its own. Task: POC-11.6 (ADR-0033)."""

from starlette.types import Message, Receive, Scope, Send

from app.core.security_headers import SECURITY_HEADERS, SecurityHeadersMiddleware


def make_app(headers: list[tuple[bytes, bytes]]) -> SecurityHeadersMiddleware:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b""})

    return SecurityHeadersMiddleware(inner)


async def run(
    app: SecurityHeadersMiddleware, scope_type: str = "http"
) -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(message: Message) -> None:
        sent.append(message)

    await app({"type": scope_type}, receive, send)
    return sent


def start_headers(sent: list[Message]) -> list[tuple[bytes, bytes]]:
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers: list[tuple[bytes, bytes]] = start["headers"]
    return headers


async def test_the_four_headers_are_added_to_a_response_that_has_none() -> None:
    # Arrange
    app = make_app([])

    # Act
    sent = await run(app)

    # Assert
    assert sorted(start_headers(sent)) == sorted(
        (name.lower().encode(), value.encode()) for name, value in SECURITY_HEADERS
    )


async def test_a_header_the_response_already_sets_keeps_its_own_value() -> None:
    # Arrange
    app = make_app([(b"cache-control", b"max-age=60")])

    # Act
    sent = await run(app)

    # Assert
    cache_control = [v for k, v in start_headers(sent) if k == b"cache-control"]
    assert cache_control == [b"max-age=60"]


async def test_a_header_is_never_added_twice() -> None:
    # Arrange
    app = make_app([])

    # Act
    sent = await run(app)

    # Assert
    names = [k for k, _ in start_headers(sent)]
    assert len(names) == len(set(names))


async def test_a_non_http_scope_passes_through_untouched() -> None:
    # Arrange
    called: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        called.append(scope["type"])

    app = SecurityHeadersMiddleware(inner)

    # Act
    await run(app, scope_type="lifespan")

    # Assert
    assert called == ["lifespan"]
