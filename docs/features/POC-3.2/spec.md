# POC-3.2 — HTTP test client

## Problem
Every e2e test that calls the app builds its own httpx client (`client_for` lives inside `tests/e2e/test_db_session.py`) and
has to remember to run the lifespan by hand, because `ASGITransport` does not. There is no helper to sign in and send the
`Authorization` header, nothing that captures the jobs an endpoint enqueues, and no clock control for token and OTP expiry
tests (rule: never sleep, `testing.md` 5). Packages 5 to 8 will each need all four.

## Goal / business value
Goal 3 (Test base, BUSINESS_MODEL.md): a test setup that "keeps working and is easy to extend". Unblocks the e2e suites of 5.3, 5.4 and 7.1 to 7.6.

## Scope
- in: a `client` fixture (httpx `AsyncClient` over `ASGITransport` on `create_app()`, lifespan entered and left); an auth helper
  (`sign_up`, `sign_in`, bearer headers) written to the contract in `docs/api/ENDPOINTS.md`; a `FakeQueue` that records jobs; a clock
  fixture on `time-machine` (dev dependency); one sample e2e test per piece; RUNBOOK note.
- **out (explicit):** the real `sign-up` / `sign-in` / refresh endpoints (7.x), JWT creation and the Bearer dependency (4.4), the
  real `QueueClient` protocol and arq (6.1), the test-conventions skill and rules (3.3), porting other tests (only `client_for` moves, behaviour unchanged), CI.

## Acceptance criteria
- [x] AC1 Given the `client` fixture, when a test calls `GET /api/v1/health`, then it gets 200 `{"status": "ok"}`; the app's lifespan startup ran before the call and shutdown ran after the test.
- [x] AC2 The auth helper posts `{email, password}` to `/api/v1/auth/sign-up` (expects 201) or `/sign-in` (expects 200), reads `{accessToken, refreshToken}` and returns headers; a stub authenticated route accepts them and answers 401 without them.
- [x] AC3 `FakeQueue` records each enqueued job (name, args, kwargs) in order and a test can read, filter and clear them; nothing reaches Redis.
- [x] AC4 Under the clock fixture `datetime.now(UTC)` returns the frozen instant and `app.core.db.utc_now()` the same instant without `tzinfo` (it is naive by design); both move only when the test moves them; no `sleep` is used.
- [x] AC5 `test_db_session.py` uses the moved `client_for` and its tests still pass unchanged.
- [x] AC6 `ruff check`, `ruff format --check`, `mypy`, `pytest tests/unit` and `pytest tests/e2e` pass; no test weakened or skipped.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| The helper gets an unexpected status from sign-up or sign-in | it fails the test with the status and body, never returns empty headers | testing.md 12 |
| An app exception inside a handler | `raise_app_exceptions=True` stays the default, as `client_for` does today; a test opting out says so | precedent |
| Postgres `CURRENT_TIMESTAMP` defaults | not moved by the clock (server time); services must pass `utc_now()`; noted in RUNBOOK | time-machine patches the process only |
| `time.monotonic` / asyncio | time-machine 3.x does not mock them, so the event loop is unaffected | time-machine changelog 3.0.0 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Sign-up/sign-in (7.3) and JWT (4.4) do not exist, so the auth helper has nothing real to call. Build it now against the ENDPOINTS.md contract and prove it with test-local stub routes, or defer it? | build now, stubs prove the plumbing; the 7.3 e2e tests are its first real consumer and may adjust it | yes, if you prefer to defer it the acceptance "authenticated stub route" cannot be met as written |
| Q2 | Add `time-machine` to the `dev` group (pyproject is ask-first, rule C2)? | yes, dev only, `uv add --dev time-machine` | yes (approval line) |
| Q3 | `FakeQueue` before the `QueueClient` protocol of 6.1 exists | `async enqueue(job_name, *args, **kwargs)`; 6.1 owns the protocol and adapts the fake | no |
| Q4 | File layout | `tests/utils/client.py`, `auth.py`, `queue.py` (the last is beyond the scope doc's list); task 3.3 may move `tests/utils/` | no |
