"""Security response headers on every response the app sends. Tasks: 11.6 (ADR-0033).

Pure ASGI, as body_limit.py: BaseHTTPMiddleware would buffer a streamed body. It is the outermost
middleware, so a 413 from the body limit and a CORS preflight carry the headers too. A response that
already sets one of them keeps its own value (a later file route may want another Cache-Control).

Not sent on purpose: Strict-Transport-Security (the app speaks plain HTTP behind whatever ends TLS,
which sets it) and Content-Security-Policy (the Swagger UI of local and development loads a script
from a CDN and inline).
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Every body is JSON or a download: nothing is meant to be sniffed, framed or cached, because
# responses carry tokens and personal data.
SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS:
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
