# POC-4.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr - 2026-11-03

Pattern followed: `app/core/body_limit.py` (one cross-cutting module per concern in `app/core/`, wired in `create_app` in `app/main.py`; its comment says task 4.2 owns the handlers) and `app/core/db.py` for `Settings`-driven setup. Tests follow `tests/e2e/test_body_limit.py` (test-local routes added to the app instance) but run as unit tests: no database, no Docker.
Layer: core (`errors.py` imports no layer, project-structure rule), composition in `main.py`. ADR-0003 already decides the contract; no new pattern, no ADR.

## Contract changes
- boundary: additive for clients that already read `{"error"}`; **changes** the body of the default 422 and of 404/405 (`{"detail"}` becomes `{"error"}`). No real route exists yet, so no consumer breaks. `openapi.json` gains an `ErrorResponse` schema and 422/500 responses.
- data: none.
- generated output: `openapi.json` by `uv run python -m app.cli --export-openapi`; never hand-edited.

<!-- Amended after the second /analyze: error responses declared on FastAPI(...) instead of the api router; test file renamed test_http_errors.py (http_ prefix); ERRORS.md says clients show no `message`. -->

## Requirements (ordered; branch `feat/POC-4.2-error-contract`, one draft PR, one commit each)

### R1 — Domain exceptions and the body builder (S)
- files: `app/core/errors.py` (new): `AppError(Exception)` with class attributes `status_code`, `code`, default `message`, instance `details`; subclasses `UnauthorizedError`, `InvalidCredentialsError`, `InvalidResetTokenError`, `EmailAlreadyRegisteredError`, `ForbiddenError`, `NotFoundError`, `ValidationFailedError`; typed without `Any` (rule D3): `type ErrorDetail = dict[str, str] | str` (a validation entry or a traceback line), Pydantic models `ErrorBody(code, message, details: list[ErrorDetail])` and `ErrorResponse(error: ErrorBody)`, a `TypedDict` `ErrorEnvelope`, and `error_body(code, message, details=()) -> ErrorEnvelope` (the one builder).
- layer: core.
- test: `tests/unit/test_errors.py` (pure, no HTTP) — each of the seven subclasses maps to the right status and code (table-driven; the eighth code, `INTERNAL_SERVER_ERROR`, has no class and is covered in R2); `error_body` shape; `details` defaults to a fresh list per instance (no shared mutable default).
- executed how: evidence = test output, plus `uv run python -c` printing `error_body` for each subclass; the real HTTP run is R2. `uv run mypy` clean with no `Any`.
- risk: none.

### R2 — Handlers and wiring (M)
- files: `app/core/errors.py` (change: `register_error_handlers(app, *, expose_trace: bool)` adds handlers for `AppError`, `RequestValidationError`, `StarletteHTTPException` (404 to `NOT_FOUND`, 401 to `UNAUTHORIZED`, 403 to `FORBIDDEN`, other statuses per spec Q1) and `Exception` (500, `logger.exception`, generic message, traceback in `details` only when `expose_trace`); validation `details` are built from `loc` and `msg` and `type` only, never `input` or `ctx`), `app/main.py` (change: call `register_error_handlers(app, expose_trace=settings.app_env == "local")`).
- layer: core plus main wiring.
- test: `tests/e2e/test_http_errors.py` (route behaviour at the HTTP boundary, no database; test-local routes on `create_app(Settings())`, client `running_client(app, raise_app_exceptions=False)` from `tests/utils/client.py`, no second client helper): one test per code (AC1, all eight, 500 included); 422 from a bad body lists `field`s (AC2); a password sent in the bad body is absent from the response and from `caplog` (AC3); 500 hides the traceback with `app_env="production"` and shows it with `local`, and the log record has `exc_info` under both (AC4); unknown path gives `NOT_FOUND` (AC5); 405 keeps its status with `VALIDATION_FAILED` (Q1, answered).
- executed how (evidence = request/response pairs plus the JSON log line): a script in the scratchpad, outside the repo, builds `create_app(Settings(app_env=...))`, adds one route raising `RuntimeError` and one taking a body model with a `password` field, calls `configure_logging`, and serves through `uvicorn.run` like `app.main.run`. Then `curl -i`: the 500 under `local` (traceback in `details`) and under `production` (none), the bad body (field names, no password), an unknown path (404) and `POST /api/v1/health` (405). Paste each response and the stdout log line (stack present, password absent).
- risk: handler order (`HTTPException` vs `Exception`) and the 500 handler running outside CORS. Cheapest check: a 500 test with an `Origin` header; the result goes into ERRORS.md. Sentry capture of 500s with a custom handler: read `app/core/sentry.py` and the installed Starlette source in R2 before relying on it (rule D4).

### R3 — One body for the 413, contract in OpenAPI (S)
- files: `app/core/body_limit.py` (change: `TOO_LARGE_BODY = error_body("VALIDATION_FAILED", "Request body too large")`, drop the "until it lands" comment; same value as today), `app/main.py` (change: `FastAPI(..., responses={422: ..., 500: ...})` using `ErrorResponse`, so routes included from routers and routes added straight to `app` (as tests do) both inherit it and the default `HTTPValidationError` is not advertised; verified by printing the OpenAPI of a test app first), `openapi.json` (regenerated).
- layer: core, main, generated file.
- test: `tests/e2e/test_body_limit.py` already asserts `TOO_LARGE_BODY`; add `tests/unit/test_errors_openapi.py` — on a `create_app(Settings())` instance with a test-local route that takes a body model (health has no parameters, so FastAPI would not add its default 422 there and the test would prove nothing): that route's 422 references `ErrorResponse`, `components.schemas` has no `HTTPValidationError`, 500 references `ErrorResponse`. `tests/unit/test_openapi_stale.py` must pass after regeneration.
- executed how: evidence = exit codes and diff: `uv run python -m app.cli --export-openapi`, second run leaves `git diff openapi.json` empty, `--check` exits 0; `uv run pytest tests/e2e/test_body_limit.py` still green (needs Docker only if its fixtures do: say so under "Not verified" if not run).
- risk: FastAPI may still add the default 422 next to a declared one (the real contract has no parameterised route yet, so only the test-local route shows it). Cheapest check: build the test app with that route and print its OpenAPI before writing the assertion; check the pinned FastAPI source or Context7 for how router `responses` merge (rule D4).

### R4 — Docs (S)
- files: `docs/api/ERRORS.md` (new: clients key on `code` and must not show `message` to end users (D7); table of codes, when each is raised, client rule for `UNAUTHORIZED`, validation `details` shape, 500 in local vs elsewhere, 404/405 mapping, upload 413/422 from mapping decision 6, how to add an exception subclass), `docs/api/ENDPOINTS.md` (change: "models and validation code come in tasks 4.2 and 4.3" wording and link to ERRORS.md), `docs/ARCHITECTURE.md` (change: `app/core/` list and "Boundaries and contracts"), `docs/features/POC-4.2/spec.md` (ACs ticked).
- layer: docs.
- test: grep that every code in `ERRORS.md` exists in `app/core/errors.py`; full gate below.
- executed how: full gate output pasted in the PR.
- risk: none.

## Quality gate (per requirement, full run at the end)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker), `uv run python -m app.cli --export-openapi --check`.

## Docs to update in this PR
- [ ] spec.md ACs; `ERRORS.md`; `ENDPOINTS.md` wording; `ARCHITECTURE.md`
- [ ] DOMAIN_GLOSSARY: no new domain term (error codes are API vocabulary, listed in ERRORS.md). ADR: none, ADR-0003 holds; Q1 would need one if a new code is chosen.

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Pydantic error dicts carry `input` (passwords) | secret in response or log | R2 test posts a password to a bad body and greps response and `caplog` |
| 500 body lacks CORS headers | browser reports CORS error instead of 500 | R2 test with an `Origin` header |
| Declared 422 plus FastAPI's default both appear | two shapes in the contract | R3 export and grep first |
| 405/other statuses have no code (Q1) | a guess becomes a contract | human answers Q1 before R2 |

## Assumptions
- A1 Messages are English developer strings, not i18n keys (the client keys on `code`). A2 No new runtime dependency (rule C2). A3 `Settings.app_env == "local"` is the only trace-exposing mode. A4 Estimate: R1 S, R2 M, R3 S, R4 S.
- The branch `feat/POC-4.2-error-contract` is cut from the updated `main`; the untracked scope doc and `.serena/` stay out of the PR.

## Blockers before approval
- none. Q1 answered by volodymyr on 2026-11-03: other statuses (405) keep their status with `VALIDATION_FAILED` and empty `details`; no new code, so no ADR. R2's 405 test and the `ERRORS.md` row follow this.
