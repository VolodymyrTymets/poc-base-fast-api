"""RequestIdMiddleware on its own. Task: POC-11.6 (ADR-0033)."""

import re

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.core.request_id import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    request_id_of,
    request_id_var,
)

GENERATED = re.compile(r"[0-9a-f]{32}")


class Probe:
    """The app under the middleware: remembers what the ContextVar and the scope held while it ran."""

    def __init__(self) -> None:
        self.var_during: str | None = None
        self.scope_during: str | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.var_during = request_id_var.get()
        self.scope_during = request_id_of(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})


async def call(
    app: RequestIdMiddleware, header: bytes | None, scope_type: str = "http"
) -> tuple[list[Message], Scope]:
    sent: list[Message] = []
    headers = [] if header is None else [(b"x-request-id", header)]
    scope: Scope = {"type": scope_type, "headers": headers}

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent, scope


def response_id(sent: list[Message]) -> str:
    start = next(m for m in sent if m["type"] == "http.response.start")
    values: list[str] = [
        v.decode()
        for k, v in start["headers"]
        if k.lower() == REQUEST_ID_HEADER.lower().encode()
    ]
    assert len(values) == 1
    return values[0]


@pytest.mark.parametrize("value", ["abc-123", "a", "A.b_c-9", "x" * 64])
async def test_a_well_formed_id_is_echoed(value: str) -> None:
    # Arrange
    probe = Probe()

    # Act
    sent, _ = await call(RequestIdMiddleware(probe), value.encode())

    # Assert
    assert (response_id(sent), probe.var_during, probe.scope_during) == (
        value,
        value,
        value,
    )


async def test_a_missing_id_is_generated() -> None:
    # Arrange
    probe = Probe()

    # Act
    sent, _ = await call(RequestIdMiddleware(probe), None)

    # Assert
    assert GENERATED.fullmatch(response_id(sent))
    assert probe.var_during == response_id(sent)


@pytest.mark.parametrize(
    "value",
    [
        b"",
        b"bad id",
        b"line\nbreak",
        b"trailing-newline\n",
        b"x" * 65,
        b"x" * 10_000,
        b"slash/inside",
        "café".encode("latin-1"),
    ],
    ids=[
        "empty",
        "space",
        "newline",
        "trailing newline",
        "65 chars",
        "10000 chars",
        "slash",
        "non-ascii",
    ],
)
async def test_a_malformed_id_is_replaced_and_never_echoed(value: bytes) -> None:
    # Arrange
    probe = Probe()

    # Act
    sent, _ = await call(RequestIdMiddleware(probe), value)

    # Assert
    assert GENERATED.fullmatch(response_id(sent))
    assert probe.var_during != value.decode("latin-1")


async def test_the_variable_is_reset_when_the_request_ends() -> None:
    # Arrange
    app = RequestIdMiddleware(Probe())

    # Act
    await call(app, b"abc-123")

    # Assert
    assert request_id_var.get() is None


async def test_the_variable_is_reset_when_the_app_raises() -> None:
    # Arrange
    async def failing(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("boom")

    app = RequestIdMiddleware(failing)

    # Act
    with pytest.raises(RuntimeError, match="boom"):
        await call(app, b"abc-123")

    # Assert
    assert request_id_var.get() is None


async def test_a_non_http_scope_passes_through_untouched() -> None:
    # Arrange
    probe = Probe()

    # Act
    _, scope = await call(RequestIdMiddleware(probe), b"abc-123", scope_type="lifespan")

    # Assert
    assert (probe.var_during, "state" in scope) == (None, False)
