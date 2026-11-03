"""Reject request bodies over a size limit with 413. Tasks: 1.6.

Pure ASGI on purpose: BaseHTTPMiddleware would buffer the body, and the limit has to stop
a stream as soon as it crosses the line. Upload-specific limits (FILE_MAX_SIZE, mime types)
stay with the files module (task 8.x); this is the global ceiling, set above them.
"""

from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ErrorCode, error_body

# Pure ASGI middleware runs before routing and cannot raise into the exception handlers, so
# it builds the same body with the same function (app/core/errors.py, ADR-0003).
TOO_LARGE_BODY = error_body(ErrorCode.VALIDATION_FAILED, "Request body too large")


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response = JSONResponse(TOO_LARGE_BODY, status_code=413)
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await response(scope, receive, send)
            return

        # State of one request, owned by the task that handles it.
        received = 0
        rejected = False  # the limit was crossed: the app gets no more bytes
        started = False  # the app has begun its own response
        answered = False  # we sent the 413: the app's own output is dropped

        async def limited_receive() -> Message:
            nonlocal received, rejected, answered
            if rejected:
                # Bytes past the limit never reach the app, whatever the server delivers next.
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] != "http.request":
                return message
            received += len(message.get("body", b""))
            if received <= self.max_bytes:
                return message
            rejected = True
            # A response that has already started cannot become a 413; the app is only
            # stopped. FastAPI turns an exception raised while reading the body into a 400,
            # so otherwise the 413 is sent here and the app is told the client went away.
            if not started:
                answered = True
                await response(scope, receive, send)
            return {"type": "http.disconnect"}

        async def guarded_send(message: Message) -> None:
            nonlocal started
            # Whatever the app answers after the 413 is dropped: one response per request.
            if answered:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except ClientDisconnect:
            # A handler that reads the body itself sees the disconnect we simulated. The
            # 413 is already sent, so that is the expected end; any other case is a real
            # disconnect and is raised.
            if not answered:
                raise
