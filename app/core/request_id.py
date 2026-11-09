"""A request id for every request, in the response header and on every log line. Tasks: 11.6 (ADR-0033).

Pure ASGI, as body_limit.py. The id comes from `X-Request-ID` when it is well formed (1 to 64 characters of
letters, digits, `.`, `_` and `-`), otherwise it is a generated uuid4 hex: a header value is client input, so
a long, spaced or multi-line one is never echoed and never logged.

The id lives in a ContextVar for the duration of the request, which is how `JsonFormatter` finds it without every
caller passing it. It is also stored in `scope["state"]["request_id"]` (what Starlette's `request.state` reads),
because Starlette's handler for an unhandled exception runs after this middleware has finished and the var is reset.
"""

import re
import uuid
from contextvars import ContextVar
from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER: Final = "X-Request-ID"
# fullmatch, not `$`: a trailing newline must not pass.
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

# One value per request, set by the middleware and reset when the request ends.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def request_id_of(scope: Scope) -> str | None:
    """The id the middleware stored for this request, for code that runs outside its ContextVar scope."""
    state = scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")
        if isinstance(value, str):
            return value
    return None


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"")
        candidate = incoming.decode("latin-1")
        request_id = candidate if _VALID_ID.fullmatch(candidate) else uuid.uuid4().hex
        # The same dict object is seen by the outer layers (Starlette's error middleware).
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
