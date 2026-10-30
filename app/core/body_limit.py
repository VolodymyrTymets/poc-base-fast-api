"""Reject request bodies over a size limit with 413. Tasks: 1.6.

Pure ASGI on purpose: BaseHTTPMiddleware would buffer the body, and the limit has to stop
a stream as soon as it crosses the line. Upload-specific limits (FILE_MAX_SIZE, mime types)
stay with the files module (task 8.x); this is the global ceiling, set above them.
"""

from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Same envelope as every other error (ADR-0003, docs/api/ENDPOINTS.md); task 4.2 owns the
# handlers, so until it lands the middleware writes the body itself.
TOO_LARGE_BODY = {
    "error": {
        "code": "VALIDATION_FAILED",
        "message": "Request body too large",
        "details": [],
    }
}


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
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if rejected or message["type"] != "http.request":
                return message
            received += len(message.get("body", b""))
            if received <= self.max_bytes:
                return message
            # FastAPI turns an exception raised while reading the body into a 400, so the
            # 413 is sent here and the app is told the client went away.
            rejected = True
            await response(scope, receive, send)
            return {"type": "http.disconnect"}

        async def guarded_send(message: Message) -> None:
            # Whatever the app answers after the 413 is dropped: one response per request.
            if not rejected:
                await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except ClientDisconnect:
            # A handler that reads the body itself sees the disconnect we simulated. The
            # 413 is already sent, so that is the expected end; any other case is a real
            # disconnect and is raised.
            if not rejected:
                raise
