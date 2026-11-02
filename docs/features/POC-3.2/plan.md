# POC-3.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving also approves Q1 (auth helper proved with stubs) and Q2 (dev dependency `time-machine`, rule C2) of spec.md.
     Approved-by: <name> · <date> -->
Approved-by:  volodymyr · 2026-11-02/

Pattern followed: `client_for`, `add_session_routes` and the lifespan use in `tests/e2e/test_db_session.py` (client, test-only routes on an app instance), and the
fixtures and `tests/utils/` of task 3.1 (`tests/conftest.py`, `tests/utils/db.py`). Facts checked with Context7: time-machine `move_to(destination, tick=...)`
fixture and 3.x not mocking `time.monotonic`; `ASGITransport` does not run the lifespan (the repo's own tests enter `app.router.lifespan_context`).

## Contract changes
- boundary: none (test code and docs; no route, setting or schema change). The auth helper encodes the `ENDPOINTS.md` contract, it does not change it.
- data: none. generated output: none. `uv.lock` changes only through `uv add --dev` (rule T3).
- test contract: new fixtures `asgi_app`, `client`, `queue`, `frozen_clock`; `client_for` moves to `tests/utils/client.py`.

## Requirements (ordered; branch `feat/POC-3.2-http-test-client`, one draft PR, one commit each)
Step 0, before R1 (riskiest unknown first, no commit of its own): `uv add --dev time-machine`, a 5-line run on 3.14 (`time_machine.travel` and the `time_machine` fixture with `move_to`/`shift`), then `uv run mypy`. If it fails, stop and report (B4); R1 to R3 do not depend on it. The dependency lands in the R4 commit.

### R1 — Client helper and fixtures (M)
- files: `tests/utils/client.py` (new: `client_for(app, *, raise_app_exceptions=True)` moved from `test_db_session.py`, and `running_client(app)`, an async context manager that enters `app.router.lifespan_context` and yields the client), `tests/conftest.py` (change: `asgi_app` builds `create_app(Settings(database_url=module_database_url))`, `client` yields `running_client`), `tests/e2e/test_db_session.py` (change: import the moved `client_for`, nothing else).
- layer: test support.
- test: `tests/e2e/test_http_client.py` — `GET /api/v1/health` through `client` returns 200 `{"status": "ok"}` (AC1); with `caplog` (`caplog.set_level(logging.INFO, logger="app.main")`, the default level would drop INFO), "application startup" is logged before the call and "application shutdown" after `running_client` exits.
- note: `client` depends on `module_database_url`, so every test using it needs Docker or `TEST_DATABASE_URL` and a module database (fits the authenticated flows, rule P8). A test that needs no database uses `running_client(create_app(Settings()))` directly.
- executed how: `uv run pytest tests/e2e/test_http_client.py tests/e2e/test_db_session.py -v` (AC1, AC5), output pasted.
- risk: fixture name clash: `test_db_session.py` has its own `app` fixture; the conftest one is named `asgi_app` so nothing is shadowed.

### R2 — Auth helper proved against stub routes (M)
- files: `tests/utils/auth.py` (new: `AuthTokens(access_token, refresh_token)` with `.headers` (`Authorization: Bearer ...`) and `.refresh_headers` (`x-refresh-token`); `sign_up(client, email, password)` expects 201, `sign_in(...)` expects 200, both parse `{accessToken, refreshToken}`; an unexpected status raises `AssertionError` with status and body).
- layer: test support.
- test: `tests/e2e/test_http_auth_helper.py` — stub `POST /api/v1/auth/sign-up|sign-in` and `GET /api/v1/_whoami` (401 without the stub's bearer token) are added to the app instance in the test, as `add_session_routes` does; the helper's headers reach `_whoami` (200) and a bare call gets 401 (AC2); a stub answering 500 makes `sign_up` raise with the status in the message.
- executed how: `uv run pytest tests/e2e/test_http_auth_helper.py -v`, output pasted. The real endpoints do not exist yet: listed under "Not verified".
- risk: the helper may not match the real 7.3 responses. Cheapest check: its parsing is derived from `ENDPOINTS.md` rows `signUp`/`signIn`; 7.3's e2e tests are the first real run.

### R3 — Fake queue (S)
- files: `tests/utils/queue.py` (new: `EnqueuedJob(name, args, kwargs)`, `FakeQueue` with `async enqueue(job_name, *args, **kwargs)`, `jobs`, `named(name)`, `clear()`), `tests/conftest.py` (change: `queue` fixture).
- layer: test support.
- test: `tests/unit/test_fake_queue.py` — order is kept, `named` filters, `clear` empties, args and kwargs are stored as given (AC3).
- executed how: `uv run pytest tests/unit/test_fake_queue.py -v`.
- risk: the real protocol (6.1) differs. Accepted, spec Q3; 6.1 adjusts the fake in its own PR.

### R4 — Clock fixture on time-machine (M)
- files: `pyproject.toml`, `uv.lock` (via `uv add --dev time-machine`), `tests/conftest.py` (change: `frozen_clock` moves the built-in `time_machine` fixture to `2026-01-01T12:00:00Z` with `tick=False` and returns it).
- layer: test support.
- test: `tests/e2e/test_frozen_clock.py` — `datetime.now(UTC)` equals the frozen instant and `app.core.db.utc_now()` equals it with `tzinfo` removed (it is naive on purpose, `app/core/db.py:44`); after `frozen_clock.shift(...)` they move by exactly that; through `client`, a stub route returning `utc_now()` shows the same naive instant (AC4).
- executed how: `uv run pytest tests/e2e/test_frozen_clock.py -v` and the whole `tests/e2e` once, to see that asyncpg and testcontainers are unaffected.
- risk: time-machine on Python 3.14 and the asyncpg/Docker clients under a frozen clock. First step: `uv add --dev time-machine`, a 5-line run, `uv run mypy`. If mypy rejects an import, stop and ask (no override, B3).

### R5 — Docs (S)
- files: `docs/RUNBOOK.md` (change: a short "HTTP tests" part: the four fixtures, the Postgres-time caveat), `docs/ARCHITECTURE.md` (change: tests row), `docs/features/POC-3.2/spec.md` (ACs ticked).
- test: none (docs); AC6 gate run in full.
- executed how: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `TEST_DATABASE_URL= uv run pytest tests/e2e`, outputs pasted.

## Docs to update in this PR
- [ ] docs/features/POC-3.2/spec.md (ACs checked), docs/RUNBOOK.md, docs/ARCHITECTURE.md (rule E1)
- [ ] DOMAIN_GLOSSARY: no new term. ADR: none (no new pattern; ADR-0006 and ADR-0008 cover the setup and the header names).
- scope doc row 3.2 status is the human's (rule E2: noted in the PR body)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| time-machine fails on 3.14 or breaks a client library | R4 | R4 first step, then the whole e2e suite |
| Auth helper drifts from the real 7.3 responses | rework in 7.3 | derived from ENDPOINTS.md; flagged in the PR |
| `FakeQueue` interface differs from 6.1's protocol | rework in 6.1 | flagged in the PR |
| Moving `client_for` changes `test_db_session.py` behaviour | AC5 | run that file before and after |

## Assumptions
- Spec Q1 to Q4 hold. Docker is running for the e2e runs. Python is the `uv` interpreter (3.14, T2). `tests/utils/` imports as `utils` (as in 3.1).
- Estimate: R1 M, R2 M, R3 S, R4 M, R5 S. Scope-doc estimate is 3 h.
