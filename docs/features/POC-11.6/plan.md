# POC-11.6 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code. -->
Approved-by: Volodymyr - 2026-11-09 (approved in chat, including A1, A3 and A4)

Pattern followed: `app/core/body_limit.py` for a pure ASGI middleware (no `BaseHTTPMiddleware`, which buffers; `http` scope only; JSON bodies built with `error_body`), `create_app` in `app/main.py` for where middleware is added and in what order, `app/core/logging.py` (`JsonFormatter`, `configure_logging`) for the log fields, `tests/unit/test_logging.py` and `tests/integration/http/test_http_*.py` with `running_client(create_app(Settings()))` (no database needed) for the tests, ADR-0020 for putting project code in the layer where it belongs (`core/` imports no layer). The new pattern (docs gating, the request-id contextvar, the security-header set) is recorded in ADR-0033 (rule D1).

## Contract changes
- boundary: `/docs`, `/redoc`, `/openapi.json` disappear outside `local` and `development`; every response gains four security headers and `X-Request-ID`. `openapi.json` must not change (no route changes, and headers are not in it).
- config: none (derived from `APP_ENV`). dependencies: none. generated output: none.

## Requirements (branch `feat/POC-11.6-hardening`, one draft PR, one commit each)

### R1 — contract pages only in local and development (S)
- files: `app/main.py` (`FastAPI(docs_url=..., redoc_url=..., openapi_url=...)` set to `None` unless `settings.app_env in {"local", "development"}`).
- first step: confirm `app.openapi()` and `uv run python -m app.cli --export-openapi --check` still work with `openapi_url=None` (the export calls `app.openapi()`), before wiring anything else.
- layer: entrypoint (`main.py` builds the app; no logic elsewhere).
- test: `tests/integration/http/test_http_docs_gating.py`: parametrised over `production` and `test` (three paths answer 404 with `{"error": {"code": "NOT_FOUND", ...}}`) and over `local` and `development` (three paths answer 200, `openapi.json` parses and lists `/api/v1/health`); a unit-level check that `create_app(Settings(app_env="production")).openapi()` still returns the same document as for `local`. No database needed (`running_client`).
- executed how: `APP_ENV=production uv run poc-base-fast-api`, `curl -i` of `/docs`, `/redoc`, `/openapi.json` and `/api/v1/health`; the same with `APP_ENV=development` (needs the two JWT secrets of 32+ characters, set in the shell, not a file) and `local`; `uv run python -m app.cli --export-openapi --check`.

### R2 — security headers (S)
- files: `app/core/security_headers.py` (pure ASGI `SecurityHeadersMiddleware`: adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on `http.response.start` unless the response already has that header), `app/main.py` (added last, so it is outermost and 413 and CORS preflight responses carry it).
- layer: `core/` (no layer import, as `body_limit.py`).
- test: `tests/unit/test_security_headers.py` (the ASGI app directly: adds the four, keeps an existing value, ignores a `lifespan` scope, adds nothing twice) and `tests/integration/http/test_http_security_headers.py` through `create_app`: 200, 404, 422, 413 and a CORS preflight each carry them; the 500 case records what really happens (A2).
- executed how: `curl -i` for each of those responses against a running server; paste the headers.

### R3 — request id (M)
- files: `app/core/request_id.py` (the `request_id_var` `ContextVar`, `RequestIdMiddleware` pure ASGI: validates `X-Request-ID` against `^[A-Za-z0-9._-]{1,64}$`, else `uuid4().hex`, sets the var for the request and resets it in `finally`, adds `X-Request-ID` to the response), `app/core/logging.py` (`JsonFormatter` adds `request_id` when the var is set), `app/main.py` (the middleware is inside the security-header one and outside the body limit, so a 413 is logged and answered with an id).
- layer: `core/`; `logging.py` may read `request_id.py` (both `core/`).
- test: `tests/unit/test_request_id.py` (the validation cases of AC4, a 10 000-character and a newline value, the var is reset after the request, a `lifespan` scope is untouched); `tests/unit/test_logging.py` gains a case with and without a request id; `tests/integration/http/test_http_request_id.py`: echo, generate, replace a malformed value and assert it is absent from the captured log, and two concurrent requests (`asyncio.gather`) log their own ids (AC6). Uvicorn's access log line is checked in the executed run, not in-process.
- executed how: run the server with JSON logging, `curl -H 'X-Request-ID: abc-123' localhost:3001/api/v1/health`, show the response header and that the log lines of that request (including uvicorn's access line) carry `"request_id": "abc-123"`; a request with a bad id; two parallel `curl`s.

### R4 — issue review (S, no code)
- Check each of I.1 to I.10 against the code or a command and write the status with its evidence into `docs/ARCHITECTURE.md` "Known constraints and landmines" (A4). Already seen: I.1 no `JWT_ACCESS_TOKEN_SECRET` in `app/` or the templates; I.2 sha256 refresh hash (7.2); I.3 `phone_number: str | None` in `AccountProfileResponse`; I.4 admin checked by `AccountRole.type == ADMIN`; I.5 worker log `***0142`; I.6 `scripts/wait_for_postgres.py` counted attempts and its test; I.7 `.env.example` has `15m`; I.9 done (PR #26); I.10 fixed in PR #29 (the two tests are `tests/integration/http/test_http_auth_helper.py` and `tests/integration/db/test_db_session.py`). I.8 stays open and carried over (rate limiting, email change without re-authentication, a repeated restore replacing the live token): out of scope for the base, listed in the RUNBOOK; its status is "open, accepted".
- A claim that cannot be confirmed is reported as such, not marked closed.
- executed how: the commands and greps used, in a table in the PR body.

### R5 — docs and ADR (S)
- files: `docs/decisions/ADR-0033-hardening-headers-docs-request-id.md`; `docs/RUNBOOK.md` ("Logging, errors and shutdown": request id and headers; the "API contract" section: `/docs` and `/openapi.json` served only for `local` and `development`); `docs/ARCHITECTURE.md` (core rows, the issue table from R4, Decided bullet); `docs/api/ENDPOINTS.md` (conventions: `X-Request-ID`, the security headers); `docs/api/ERRORS.md` if the 500 finding changes its limitation text; `docs/DOMAIN_GLOSSARY.md` (request id); spec ACs ticked.
- executed how: follow the changed RUNBOOK lines once.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest -m "not db and not redis"` (the new tests need no Docker), `uv run pytest -m "not e2e"` (Docker) and `uv run pytest tests/e2e` for the shutdown test, `uv run python -m app.cli --export-openapi --check`, `uv build`; CI's three jobs green on the PR.

## Docs to update in this PR
- [ ] docs/features/POC-11.6/spec.md (ACs) · [ ] ADR-0033 · [ ] RUNBOOK · [ ] ARCHITECTURE (rows, issue table) · [ ] ENDPOINTS.md · [ ] DOMAIN_GLOSSARY.md · [ ] `.claude/rules/api-rest.md` and `backend-fastapi.md` (one line each for the header set and the request id; ask-first paths, only with confirmation)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| the `ContextVar` does not reach uvicorn's access log line (it is written outside the app's task) | AC5 half true | run R3's executed check first, before the tests; if it does not, the access line gets the id another way or the limit is documented |
| middleware order: a 413 or a CORS preflight answered before our middleware | headers or id missing there | the integration tests list those cases explicitly |
| `X-Frame-Options`/`no-referrer` break the Swagger page | the dev UI stops working | open `/docs` in the executed run for `local` |
| `Cache-Control: no-store` hurts a later file download | files re-downloaded each time | a response's own header wins (AC3); task 8.3 can set a different one |
| a test or doc relies on `/docs` in an environment now off | red test | `grep -rn "/docs\|/openapi.json" tests docs` before R1 |

## Assumptions
- A1-A5 of the spec; whoever writes `Approved-by:` also confirms A1 (`test` is off) and A3 (no HSTS, no CSP).

## Estimate
R1 S · R2 S · R3 M · R4 S · R5 S
