# ADR-0033 — Hardening: contract pages in local and development only, four security headers, a request id

- **Date:** 2026-11-09
- **Status:** accepted
- **Deciders:** Volodymyr
- **Ticket:** POC-11.6
- **Supersedes:** nothing. It adds two files to `app/core/` (rule 3 of ADR-0011: one module per concern) and changes what `create_app` serves; ADR-0003's contract and `openapi.json` are unchanged.

## Context
The app served the Swagger UI, ReDoc and `/openapi.json` in every environment, sent no security headers, and its log lines could not be tied to a request. The scope row (task 11.6) asked for the first two to be fixed and for a request id in the logs.

## Decision
- **Contract pages.** `create_app` passes `docs_url`, `redoc_url` and `openapi_url` to FastAPI only when `APP_ENV` is `local` or `development` (`CONTRACT_PAGE_ENVS` in `app/main.py`); otherwise they are `None` and the three paths are an ordinary 404 with the error body. No new setting: the environment already says how exposed the app is. `app.openapi()` does not need the served route, so `python -m app.cli --export-openapi` and the stale-spec test are unaffected (a test proves the exported document is identical in every environment). `test` is off, as the scope row names only `local` and `development`.
- **Security headers.** `app/core/security_headers.py`, a pure ASGI middleware (as `body_limit.py`), adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store` to every response the app sends, unless the response already sets that header (a later file route may choose another `Cache-Control`). Responses carry tokens and personal data, and nothing here is meant to be framed or cached. It sits second from the outside, so a 413 from the body limit and a CORS preflight carry the headers.
- **Not sent, on purpose.** `Strict-Transport-Security`: the app speaks plain HTTP behind whatever ends TLS, which sets it, and a browser ignores it over HTTP. `Content-Security-Policy`: the Swagger UI of local and development loads a script from a CDN and inline, so a policy that fits it is a policy that protects little; the API's own responses are JSON.
- **Request id.** `app/core/request_id.py`, a pure ASGI middleware that is the outermost layer. It takes `X-Request-ID` when it is 1 to 64 characters of `A-Za-z0-9._-` (a full match, so a trailing newline fails), otherwise a generated uuid4 hex; it puts the id in a `ContextVar` for the request, in `scope["state"]["request_id"]`, and in the response header. A malformed value is replaced, never echoed and never logged: it is client input. `JsonFormatter` adds `request_id` to every record written while the var is set, which includes uvicorn's access line (checked on a running server). A record that already carries `request_id` keeps it.
- **The unhandled 500.** Starlette answers an unhandled exception in its outermost middleware, which runs after ours has finished and reset the var, and outside it. The handler therefore reads the id from `scope["state"]`, logs it with the `unhandled error` line and returns it in `X-Request-ID`: the pair an incident is followed by. The same position means that response carries none of the four security headers (and no CORS headers, ERRORS.md); a test records that, and the docs say so. Restructuring the middleware stack to change it is not part of this task.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| A `DOCS_ENABLED` setting | one more variable to forget; `APP_ENV` already carries the meaning and the scope row names the environments |
| `BaseHTTPMiddleware` for either middleware | it buffers a response body, which a later file download would pay for (ADR-0009, as `body_limit.py`) |
| Resetting nothing: leave the id in the var after the request | a client that runs the app in the caller's task (tests, `httpx.ASGITransport`) would leak one request's id into the next; the 500 path reads the scope instead |
| An id taken from `X-Forwarded-*` or a trace header | no proxy or tracing is defined (no environment, rule C5) |
| The id as a logging `Filter` | the formatter already runs on the final record in every handler (rule P4's redaction lives there), so one place does both |

## Consequences
- A client may send any id of the allowed shape: it is a correlation hint, never trusted for anything else, and it is not secret.
- Worker jobs do not carry the id: a job started by a request logs without one. Passing it as a job argument is a follow-up.
- `Cache-Control: no-store` on every response means a browser or proxy never reuses a response, a download included, until a route sets its own header.
- The Sentry events do not get a `request_id` tag yet.

## Revisit when
A proxy or tracing system is defined (its id should win over a generated one), a file download needs caching, a web client returns and needs a CSP, or the 500 path must carry CORS and the security headers (that moves the catch inside the middleware stack).
