---
description: Python testing rules for this repo - tests/unit vs tests/e2e, file naming, the fixtures of tests/conftest.py, what may be mocked, determinism, markers and skips.
paths:
  - "**/test_*.py"
  - "**/*_test.py"
  - "**/tests/**"
  - "**/conftest.py"
  - "pytest.ini"
  - "pyproject.toml"
---

# Python testing rules

These add pytest mechanics to the language-neutral rules in `testing.md`; if they conflict, `testing.md` wins and you raise it.
They are written for this repo (task 3.3). The skill `test-conventions` has a copy-paste unit example and e2e example; the
fixtures themselves are documented in `tests/conftest.py` and `docs/RUNBOOK.md` ("Database tests", "HTTP tests"). Extend what
exists (rule D1): no second client helper, no second fake queue, no second clock.

## Levels and layout
1. **`tests/unit/` needs nothing outside the process**: no Docker, no database, no network, no Redis. If a test needs the database or
   the app served over HTTP, it is e2e. Today no unit test uses a database fixture; keep it so.
2. **`tests/e2e/` runs against a real Postgres** (rule P8, ADR-0006), through the fixtures below, and the app over HTTP where it
   calls an endpoint. A mocked or in-memory database is never an e2e test and never a substitute for one.
3. One behaviour at one level (`testing.md` 2). A pure rule (parsing, hashing, redaction, a token's claims) is unit. A route,
   a query, a constraint, a transaction or a migration is e2e.
4. Files are flat under `tests/unit/` and `tests/e2e/`, named `test_<subject>.py`. A test of one module of a layer is
   `test_<module>_<layer>.py` (`test_account_service.py`, `test_account_models.py`), so a router and a service called `account`
   never collide. In e2e the same module gets a `db_` prefix (`test_db_account_models.py` beside the unit `test_account_models.py`)
   and an HTTP test of it an `http_` one (`test_http_client.py`). A file name is unique across both directories: `tests/`,
   `tests/unit/` and `tests/e2e/` have no `__init__.py`, so a duplicate basename stops collection. A `core/` concern is `test_<concern>.py` (`test_logging.py`). An e2e flow is named for the flow
   (`test_sign_in.py`, `test_refresh_token.py`). Split a directory by area only when it passes about 20 files, in its own PR.
5. Shared helpers live in `tests/utils/` and are imported as `utils.<module>` (rootdir `conftest.py`; `tests/utils/` is the only package, it has an `__init__.py`);
   fixtures used by several files live in `tests/conftest.py`; a fixture used once stays beside its test.
6. **Tests are `async def` when they await.** `asyncio_mode = "auto"` is set: no `@pytest.mark.asyncio`, no event-loop fixture.

## The fixtures (all in `tests/conftest.py`)
7. Pick by what the test needs, the smallest first:
   | Need | Use |
   |------|-----|
   | rows written and read back, constraints, services that take a session | `db_session` (rolled back after each test, commits included) |
   | a connection of its own or checks across connections | `db_engine` (commits stay for the module) |
   | the app over HTTP | `client` (lifespan run), with `asgi_app` when the test adds a route or inspects the app |
   | the app over HTTP with no database | `running_client(create_app(Settings()))` from `utils.client` |
   | a signed-in caller | `sign_up` / `sign_in` from `utils.auth` (`.headers`, `.refresh_headers`) |
   | the jobs an endpoint or service enqueued | `queue` (`FakeQueue`: `jobs`, `named(...)`, `clear()`) |
   | tokens, codes or links that expire | `frozen_clock` (`frozen_clock.shift(timedelta(...))`) |
   The database fixtures start Docker on first use, or use `TEST_DATABASE_URL`; they fail loudly, never skip.
8. `module_database_url` gives each test module its own database, so rows from a committing test stay until the module ends. Do not
   rely on another test's rows or on test order; create what the test needs (`testing.md` 10).
9. An autouse fixture runs every test from an empty temp directory with the app's environment variables cleared. Set what a
   test needs with `monkeypatch.setenv` or `Settings(...)`; never write into the repo, the home directory or a shared path
   (`tmp_path` for files).
10. A fixture is a `yield` fixture for teardown, never `try/finally` in a test. Scope function unless it is expensive and
    immutable (`module` and `session` ones exist already). A factory fixture (a function the test calls with overrides)
    beats several near-identical fixtures.

## Mocking and fakes
11. **Mock only the boundary**, and nothing you own and can run cheaply (`testing.md` 3): the clock, the job queue, outbound
    network, SMS and email providers, randomness. **Never mock the database** (P8), the session, a service in a router test, or
    the unit under test.
12. Use what exists before writing a fake: `frozen_clock` for time, `FakeQueue` for jobs. The app does not use the queue
    until task 6.1, so until then a test route that needs it calls `queue.enqueue(...)` itself.
13. A new boundary gets a small hand-written fake (same interface, fails loudly on a wrong call) in `tests/utils/`, not
    `MagicMock`. When `mock` is unavoidable, use `create_autospec` or `spec=True` and assert on the effect. Patch where the code
    under test looks the name up (`monkeypatch.setattr(module_under_test, "name", fake)`), not where it is defined.
14. **Clock and randomness:** prefer an injected `now` or a `random.Random(seed)`; under the app, use `frozen_clock`. It moves
    this process only: Postgres `CURRENT_TIMESTAMP` still reads the server's clock, so code under test passes `utc_now()`.
    List `frozen_clock` after the database fixtures in the arguments, so the first-use container start runs on the real clock.
    Never `time.sleep` or `asyncio.sleep` to wait for time to pass; shift the clock, or poll a condition with a bound.

## Writing the test
15. **Plain `assert`**, no `unittest.TestCase`. Assert on values with the real diff (`assert result == expected`),
    `pytest.raises(X, match=...)` for errors, `pytest.approx(x, abs=tol)` for floats. A bare `assert ok` hides the cause
    (`testing.md` 12).
16. **`@pytest.mark.parametrize`** for one behaviour over several inputs, with readable `ids=`. No loops or `if` in a test body.
17. Name the behaviour (`test_rejects_a_password_over_72_bytes`), one assertion subject per test, arrange/act/assert apart.
    An HTTP test asserts status and body together (`assert (response.status_code, response.json()) == (...)`).
18. Test code is typed (mypy checks `tests/`); full annotations are not needed on a one-line helper, but never `# type: ignore`
    without a human-approved `# WHY:` (S3).
19. Never log or assert on a real secret, token, password, DOB or phone number from a fixture; use obviously fake values
    (`a@example.test`, `+380000000001`) (rule D8, P4).

## Markers, skips, flakiness
20. `--strict-markers` is on and **no custom marker is registered yet**. A new marker goes into `pyproject.toml`
    (ask-first file) in the same PR, with a line saying what it excludes and how to run it.
21. **No `skip`, `skipif`, `xfail` or `pytest.skip()` without a human-approved `# WHY:` and a ticket** (rule B3). Missing Docker
    is a failure with a message, not a skip.
22. A flaky test is fixed or quarantined with a ticket in the same PR. `pytest-rerunfailures` or re-running until green is a
    rule B3 violation.
23. Coverage is a diagnostic (`uv run pytest --cov=app`, by hand): read the uncovered branches of the code you changed, and do
    not add tests to move a number.

## Bugs
24. A bug fix starts with a test that fails for the right reason (`fix-bug` skill); show the failing run and the passing run.
