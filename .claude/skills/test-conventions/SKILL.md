---
name: test-conventions
description: Use when writing or changing a test in this repo - choosing unit vs e2e, naming the file, picking a fixture (db_session, client, queue, frozen_clock), deciding what may be mocked. Has a runnable unit example and e2e example to copy.
---

# Test conventions (pytest)

The rules are in `.claude/rules/testing-python.md` (read it; it is short). This skill is the quick path: which level, which fixture,
and two examples that run. Rules that apply here: P8 (real Postgres, never a mocked database), B3 (never weaken a test: no
`skip`/`xfail` without `WHY:`), D8/P4 (no real secrets or personal data in tests).

## 1. Pick the level and the fixtures

| You are testing | Level and file | Use |
|-----------------|----------------|-----|
| a pure rule: parsing, hashing, redaction, token claims, a settings check | `tests/unit/test_<module>_<layer>.py` | plain asserts, `parametrize`; `frozen_clock` for time |
| rows, constraints, a service with a session, a migration | `tests/e2e/test_db_<module>_<layer>.py` | `db_session` (rolled back after each test) |
| an endpoint, status codes, headers, the error body | `tests/e2e/test_http_<subject>.py` or `test_<flow>.py` | `client` (and `asgi_app` to add a test-only route) |
| a caller who is signed in | e2e | `sign_up` / `sign_in` from `utils.auth` -> `.headers` |
| jobs an endpoint or service enqueues | e2e | `queue` (`named(...)`, `jobs`) |
| a code, token or link that expires | unit or e2e | `frozen_clock.shift(timedelta(...))`, never `sleep` |

- Needs Docker, the database or the app over HTTP: **e2e**. Needs none of them: **unit**.
- File names are **unique across `tests/unit` and `tests/e2e`** (`tests/`, `tests/unit/` and `tests/e2e/` have no `__init__.py`; a duplicate basename stops
  collection). Unit `test_account_models.py` and e2e `test_db_account_models.py`; e2e `test_http_client.py`, `test_sign_in.py`.
- Mock only the boundary: clock, queue, outbound network, SMS/email. Never the database, the session, or the unit under test.
- Tests are `async def` when they await; there is no asyncio marker (`asyncio_mode = "auto"`).
- E2E tests need Docker, or `TEST_DATABASE_URL`; without either they fail with a message. They are never skipped.

## 2. Unit example (copy into `tests/unit/test_<module>_<layer>.py`)

`parametrize` with `ids`, asserting on the secret that must not leak; a time rule on `frozen_clock`. Needs no Docker.

```python
from datetime import timedelta

import pytest
from time_machine import TimeMachineFixture

from app.core.db import utc_now
from app.core.logging import REDACTED, redact

RESET_TOKEN_TTL = timedelta(minutes=30)


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("password=hunter2 ok", "hunter2"),
        ("Authorization: Bearer abc.def-123", "abc.def-123"),
        ("call +1 (555) 010-9999 now", "555"),
    ],
    ids=["password", "bearer-token", "phone-number"],
)
def test_redact_removes_the_secret(text: str, secret: str) -> None:
    redacted = redact(text)

    assert secret not in redacted
    assert REDACTED in redacted


def test_a_reset_window_closes_after_its_time_to_live(
    frozen_clock: TimeMachineFixture,
) -> None:
    # Stand-in for a service rule: real code takes the instant from utc_now(), never from the database.
    expires_at = utc_now() + RESET_TOKEN_TTL

    frozen_clock.shift(RESET_TOKEN_TTL + timedelta(seconds=1))

    assert utc_now() > expires_at
```

## 3. E2E example (copy into `tests/e2e/test_<flow>.py`)

A real row through `db_session`, and a request through `client` on a test-only route that enqueues a job (one subject per test: the response, then the side effect). The route is added to
`asgi_app` for this test only. The app does not use the queue until task 6.1, so the route calls `queue.enqueue` itself; once 6.1
lands, assert on the real endpoint and drop the stub route.

```python
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.queue import FakeQueue

from app.core.db import utc_now
from app.models import Account


async def test_an_account_row_is_written_and_read_back(
    db_session: AsyncSession,
) -> None:
    db_session.add(Account(id="example-account", last_login_at=utc_now()))
    await db_session.commit()

    found = (
        await db_session.execute(select(Account).where(Account.id == "example-account"))
    ).scalar_one()

    assert found.deleted is False


@pytest.fixture
def example_route(asgi_app: FastAPI, queue: FakeQueue) -> None:
    # The app does not use the queue until task 6.1, so the test route calls it itself.
    @asgi_app.post("/api/v1/_example", status_code=202)
    async def example() -> dict[str, str]:
        await queue.enqueue("example_job", "+380000000001")
        return {"status": "queued"}


@pytest.mark.usefixtures("example_route")
async def test_the_request_is_accepted(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/_example")

    assert (response.status_code, response.json()) == (202, {"status": "queued"})


@pytest.mark.usefixtures("example_route")
async def test_the_request_enqueues_one_job(
    client: httpx.AsyncClient, queue: FakeQueue
) -> None:
    await client.post("/api/v1/_example")

    assert [job.args for job in queue.named("example_job")] == [("+380000000001",)]
```

For a signed-in caller use `utils.auth` (`sign_up`, `sign_in`; their tests show the stub-route pattern until task 7.3 provides the
real endpoints). Existing tests to imitate: `tests/unit/test_logging.py`, `tests/e2e/test_db_account_models.py`,
`tests/e2e/test_http_client.py`, `tests/e2e/test_frozen_clock.py`.

## 4. Before you finish
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e`: all
  green, and report the real output (rule B2).
- A bug fix starts with a test that fails for the right reason; show it failing, then passing (rule B5, `fix-bug` skill).
- Do not make a red test pass by loosening an assertion, skipping it, or re-running until green (rule B3).
