# POC-1.6 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving confirms the assumed answers in spec.md (edit them first to change one), including the new runtime dependency
     `sentry-sdk` (rule C2), the decision to send redacted runtime errors to Sentry (F2, spec Q1) and the ask-first edit
     to `pyproject.toml`. Format:
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-10-30

Pattern followed: `app/config.py` + `app/main.py` + `tests/e2e/test_health.py` from POC-1.4 (settings validated once in `Settings`,
`create_app(settings)` wires middleware, tests build the app with explicit `Settings(...)` so a developer's `.env` never leaks in).
Cross-cutting code goes in `app/core/logging.py` (ADR-0011, project-structure rule 3); `core` may read `config`, imports no layer.
No Python precedent exists for Sentry or ASGI middleware; both are library mechanics, checked with Context7 (rule D4) before use:
`sentry_sdk.init` options, Starlette/ASGI `receive` wrapping, uvicorn `timeout_graceful_shutdown`.

## Contract changes
- boundary: any request with a body over `MAX_REQUEST_BODY_BYTES` now gets 413 (additive; no consumer yet). Documented in ENDPOINTS.md.
- data: none. generated output: `uv.lock` by `uv add sentry-sdk` (never by hand, T3).
- config: `Settings` gains `log_level`, `sentry_dsn`, `max_request_body_bytes`, `shutdown_timeout_seconds`; all have defaults, so no existing env breaks.

## Requirements (ordered, one commit each; branch `feat/POC-1.6-logging-sentry-limits`, one draft PR)

### R1 — JSON logging with redaction (M)
- files: `app/core/logging.py` (new: `Redactor` (reusable as a function `redact(value)` and `redact_mapping(obj)` for nested dicts and lists), `JsonFormatter`, `configure_logging(level)`), `app/config.py` (change: `log_level: Literal["DEBUG","INFO","WARNING","ERROR"] = "INFO"`), `tests/conftest.py` (change: `isolated_settings_env` also clears `LOG_LEVEL`, `SENTRY_DSN`, `MAX_REQUEST_BODY_BYTES`, `SHUTDOWN_TIMEOUT_SECONDS`), `tests/unit/test_logging.py` (new), `tests/unit/test_config.py` (change: `LOG_LEVEL=nope`, `MAX_REQUEST_BODY_BYTES=0` and `SHUTDOWN_TIMEOUT_SECONDS=0` each raise `ValidationError`; AC7).
- layer: core. Redaction runs in the formatter on the final message, `extra` fields and formatted traceback, so no handler path can skip it.
- test: parametrised over JWT, `Bearer x`, `password=x`, `"ssn": "123-45-6789"`, phone, DOB key; non-sensitive text unchanged; traceback containing a token is redacted; output parses as JSON with the four fields; the config cases above.
- executed how: `uv run python -I -c` that calls `configure_logging`, logs `token=eyJ...` and prints the line (must show `[REDACTED]`).
- risk: regexes over- or under-match. The test table is the contract; documented as best effort.

### R2 — Sentry gate with redaction (M)
- files: `app/core/sentry.py` (new: `init_sentry(settings) -> bool`; passes `before_send` and `before_breadcrumb` that walk the WHOLE event or breadcrumb recursively - key-name match on every dict (`redact_mapping`, from R1) and `redact` on every string, so `request.data`, `request.headers`, `query_string`, `contexts`, `tags`, `extra` and `breadcrumb.data` are all covered - plus `data_collection` with every automatic channel off, which replaced `send_default_pii`, `include_local_variables` and `max_request_body_size` during R2 (the SDK deprecates the first; ADR-0013); `before_send` also drops `logentry.params`), `app/config.py` (change: `sentry_dsn: str | None`, blank -> None), `pyproject.toml` + `uv.lock` (`uv add sentry-sdk`), `app/main.py` (change: call in `create_app` before the app is built), `tests/unit/test_sentry.py` (new), `docs/decisions/ADR-0013-sentry-error-reporting.md` (new: Sentry as the error sink, off for `local` and without DSN, whole-event redaction hooks, no request bodies or local variables, exactly what leaves the process; notes that the 413 body carries the same `{"error": {...}}` shape as ADR-0003 with an empty `details`, so 4.2 does not read it as a contract break).
- layer: core, called from `main.py`.
- test: with `sentry_sdk.init` replaced at the seam (`monkeypatch.setattr` on the name `app.core.sentry` looks up): not called for `local`, not called for no/blank DSN, called once for `production` + DSN with `send_default_pii=False`, `include_local_variables=False` and both hooks set; the `before_send` hook given an event whose `request.data` holds a password, phone and SSN, whose `request.headers` holds `x-refresh-token`, whose `query_string`, `extra`, `contexts` and `tags` each hold a sensitive value and whose message holds a JWT, and `before_breadcrumb` given a breadcrumb whose `data` holds a JWT, return every one `[REDACTED]` (`x-refresh-token` is in the key list); malformed DSN propagates.
- executed how: `uv run python -I -c` building `Settings(app_env="local", sentry_dsn="https://k@o.ingest.sentry.io/1")` and printing the return value (False), then `production` (True). No event is sent: no network call is made by `init`.
- risk: wheel for Python 3.14 (stop and report if `uv add` fails, T2/F2). Sentry's default logging and Starlette integrations read records outside our formatter; the hooks are the single exit guard, and the implementer confirms the defaults with Context7 (D4). The PR body gives `sentry-sdk` size, licence and maintenance notes (python-tooling 5).

### R3 — Request body limit (M)
- files: `app/core/body_limit.py` (new: pure-ASGI `BodyLimitMiddleware`), `app/config.py` (change: `max_request_body_bytes: int = Field(default=12582912, gt=0)`), `app/main.py` (change: `add_middleware`, registered BEFORE `CORSMiddleware` so CORS stays outermost and a 413 still carries `access-control-allow-origin`), `tests/e2e/test_body_limit.py` (new), `tests/unit/test_config.py` covers the setting (see R1).
- layer: core, wired in `main.py`. Pure ASGI, not `BaseHTTPMiddleware`, so streaming is not buffered.
- test: `Content-Length` over the limit -> 413 and a handler stub is never reached; body at exactly the limit -> 200; chunked body (generator, no `Content-Length`) over the limit -> 413; lying `Content-Length` -> 413; a 413 to an `Origin: http://localhost:5173` request carries `access-control-allow-origin`; 413 body is `{"error": {"code": "VALIDATION_FAILED", "message": "Request body too large", "details": []}}`. A test-only POST route is added to a local `FastAPI` instance, not to the app.
- executed how: start `uv run poc-base-fast-api` with `MAX_REQUEST_BODY_BYTES=1024`, `curl -i -X POST --data-binary @<2 KiB file in scratchpad> localhost:3001/api/v1/health` (expect 413; the route is GET-only so also run an in-limit POST and show 405, proving the limit runs before routing).
- risk: a middleware that has already sent headers cannot switch to 413. Mitigation: the streaming path only applies before the app responds; test covers it.

### R4 — Graceful SIGTERM and logging wiring (M)
- files: `app/main.py` (change: `run()` calls `configure_logging`, passes `log_config=None` and `timeout_graceful_shutdown=settings.shutdown_timeout_seconds` to `uvicorn.run`; lifespan logs start and stop), `app/config.py` (change: `shutdown_timeout_seconds: int = Field(default=10, ge=1)`), `tests/e2e/test_shutdown.py` (new).
- layer: `main.py` wires; no logic.
- test: spawn `sys.executable -c "from app.main import run; run()"` with `PORT` set to a free port in its environment (subprocess boundary per testing-python rule 9; the autouse fixture runs tests from an empty temp dir, so no `uv run`), wait for health, send SIGTERM, assert the process ends with the SIGTERM status (-15; uvicorn re-raises the signal after shutting down, so not 0) within the timeout and that stdout holds only JSON lines including the startup and shutdown messages. No `skipif`: no Windows target exists here (B3).
- executed how: the same by hand: start in background, `curl` health, `kill -TERM <pid>`, show exit code and the last log lines; then repeat with an in-flight slow request is NOT done (no slow route exists; stated under Not verified).
- risk: uvicorn's own `uvicorn.error` logger keeps its format if `log_config` is left on. Cheapest check: run the executed step and read the output.

### R5 — Env templates, docs, final gate (S)
- files: `.env.example`, `.env.development.example` (change: the four variables), `docs/ARCHITECTURE.md` (Current: `core/` modules, body limit; External integrations: a Sentry row with its failure mode and that it is off for `local`; Decided: ADR-0013), `docs/RUNBOOK.md` (variables, SIGTERM behaviour), `docs/api/ENDPOINTS.md` (the `VALIDATION_FAILED` row: 413 for any oversized body, not only an upload; `MAX_REQUEST_BODY_BYTES`), `docs/features/POC-1.6/spec.md` (ACs ticked).
- test: whole command map once on the final tree (`ruff check`, `ruff format --check`, `mypy`, `pytest tests/unit`, `pytest tests/e2e`, `uv build`); `git diff --stat main` shows only the listed files.
- executed how: paste the full output into the PR.

## Docs to update in this PR
- [ ] docs/features/POC-1.6/spec.md (ACs ticked) · [ ] docs/ARCHITECTURE.md · [ ] docs/RUNBOOK.md · [ ] docs/api/ENDPOINTS.md
- [ ] docs/DOMAIN_GLOSSARY.md — none · [ ] ADR-0013 (R2): Sentry is an outside service
- not edited here, for the human: the scope-doc row 1.6 status.

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Redaction misses a shape | sensitive value in a log (P4) | table-driven test in R1; docs say best effort and callers must still not log secrets |
| `sentry-sdk` has no 3.14 wheel or pulls many deps | blocks R2 | `uv add` is the first step of R2; stop and report |
| uvicorn keeps its own log config and bypasses the JSON formatter | un-redacted, unstructured server logs | R4 executed run shows every line is JSON |
| Sentry sends an unredacted value (its integrations bypass our formatter) | sensitive value leaves the process (P4, F2) | R2 hook tests with JWT, phone, SSN in an event and a breadcrumb |
| Body-limit middleware breaks streaming or later multipart upload (8.x) | wrong 413 or buffered uploads | R3 pure-ASGI plus the chunked test; limit is above `FILE_MAX_SIZE` |

## Assumptions
- The open questions in spec.md hold as written; `Approved-by:` confirms them and the `sentry-sdk` dependency.
- The gate's BLOCK findings (Sentry bypass, Windows skip) and its should-fix items are resolved above; Context7 checks of Sentry defaults, `timeout_graceful_shutdown` and `log_config=None` are still owed at implementation (D4).
- The `uv run ruff check` / `mypy` / `pytest` allow entries from POC-1.4 already cover every command here; `.claude/settings.json` is not edited.
- `pyproject.toml` is ask-first; the only change is the `uv add sentry-sdk` line.
- CI is not touched (T4). Estimate: R1 M, R2 M, R3 M, R4 M, R5 S - about one working day against the scope doc's 3 h; the PR body says so and the human decides whether to split (F2).
- Python is the interpreter `uv` selects from `.python-version` (3.14); system `python3` (3.9) is never used (T2).
