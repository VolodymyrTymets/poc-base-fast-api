---
name: test-conventions
description: Use when writing or changing a test in this repo - choosing unit, integration or e2e, naming the file, picking a fixture (db_session, client, queue, frozen_clock), writing Arrange-Act-Assert, deciding what may be mocked. Has runnable unit and integration examples to copy.
---

# Test conventions (pytest)

The rules are in `.claude/rules/testing-python.md` (read it; it is short). This skill is the quick path: which level, which fixture,
and examples that run. Rules that apply here: P8 (real Postgres, never a mocked database), B3 (never weaken a test: no
`skip`/`xfail` without `WHY:`), D8/P4 (no real secrets or personal data in tests). The three levels are ADR-0029.

## 1. Pick the level and the fixtures

| You are testing | Level and file | Use |
|-----------------|----------------|-----|
| a pure rule: parsing, hashing, redaction, token claims, a settings check | `tests/unit/test_<module>_<layer>.py` | plain asserts, `parametrize`; `frozen_clock` for time |
| rows, constraints, a service with a session, a migration, a seed | `tests/integration/db/test_db_<module>_<layer>.py` | `db_session` (rolled back after each test) |
| an endpoint, status codes, headers, the error body | `tests/integration/http/test_http_<subject>.py` or `test_<flow>.py` | `client` (and `asgi_app` to add a test-only route) |
| a caller who is signed in | integration/http | `sign_up` / `sign_in` from `utils.auth` -> `.headers` |
| jobs an endpoint or service enqueues | integration | `queue` (`named(...)`, `jobs`) |
| a code, token or link that expires | unit or integration | `frozen_clock.shift(timedelta(...))`, never `sleep` |
| the server's start-up or shutdown, the real worker, a project command | `tests/e2e/test_<subject>.py` | a subprocess; `redis_settings` for the worker |

- Needs Docker, the database or the app over HTTP: **integration**. Needs a process of its own: **e2e**. Needs none of them: **unit**.
- Markers are set for you from the folder and the fixtures; write none. `uv run pytest -m unit` on save, `-m "not e2e"` before a push, `-m "not db and not redis"` with no Docker.
- File names are **unique across all test folders** (`tests/` and its subfolders have no `__init__.py`; a duplicate basename stops
  collection). Unit `test_account_models.py` and integration `test_db_account_models.py`; `test_http_client.py`, `test_sign_in.py`.
- Mock only the boundary: clock, queue, outbound network, SMS/email. Never the database, the session, or the unit under test.
- Tests are `async def` when they await; there is no asyncio marker (`asyncio_mode = "auto"`).
- Integration and e2e tests need Docker, or `TEST_DATABASE_URL`; without either they fail with a message. They are never skipped.

## 2. Arrange - Act - Assert

Every test has three blocks, separated by a blank line and labelled `# Arrange`, `# Act`, `# Assert`. The labels are section markers, not
explanations. **One Act per test**: a second Act is a second test. Setup that repeats goes into a fixture or `tests/utils/`. A test of a single statement may drop the labels.

## 3. Unit example (copy into `tests/unit/test_<module>_<layer>.py`)

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
    # Arrange: the parameters hold the text and the secret.

    # Act
    redacted = redact(text)

    # Assert
    assert secret not in redacted
    assert REDACTED in redacted


def test_a_reset_window_closes_after_its_time_to_live(
    frozen_clock: TimeMachineFixture,
) -> None:
    # Arrange: real code takes the instant from utc_now(), never from the database.
    expires_at = utc_now() + RESET_TOKEN_TTL

    # Act
    frozen_clock.shift(RESET_TOKEN_TTL + timedelta(seconds=1))

    # Assert
    assert utc_now() > expires_at
```

## 4. Integration examples

**Database** (copy into `tests/integration/db/test_db_<module>_<layer>.py`): a real row through `db_session`.

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utc_now
from app.models import Account


async def test_an_account_row_is_written_and_read_back(
    db_session: AsyncSession,
) -> None:
    # Arrange
    db_session.add(Account(id="example-account", last_login_at=utc_now()))
    await db_session.commit()

    # Act
    found = (
        await db_session.execute(select(Account).where(Account.id == "example-account"))
    ).scalar_one()

    # Assert
    assert found.deleted is False
```

**HTTP** (copy into `tests/integration/http/test_http_<subject>.py`): a request through `client` on a test-only route that enqueues a job (one subject per test: the response, then the side effect).
The route is added to `asgi_app` for this test only. The app has a `get_queue` dependency (`app.state.queue`, an `ArqQueueClient`); a test that wants the fake sets
`asgi_app.dependency_overrides[get_queue] = lambda: queue`. The stub route below calls `queue.enqueue` itself because no real endpoint enqueues yet; once one does, assert on that endpoint
and drop the stub. A test of the real client or worker uses the `redis_settings` fixture (real Redis, database 15 only; see the RUNBOOK) in `tests/e2e/test_worker_arq.py`.

```python
import httpx
import pytest
from fastapi import FastAPI
from utils.queue import FakeQueue


@pytest.fixture
def example_route(asgi_app: FastAPI, queue: FakeQueue) -> None:
    # No real endpoint enqueues yet (6.2 and later), so the test route calls the queue itself.
    @asgi_app.post("/api/v1/_example", status_code=202)
    async def example() -> dict[str, str]:
        await queue.enqueue("example_job", "+380000000001")
        return {"status": "queued"}


@pytest.mark.usefixtures("example_route")
async def test_the_request_is_accepted(client: httpx.AsyncClient) -> None:
    # Arrange: the example_route fixture added the route.

    # Act
    response = await client.post("/api/v1/_example")

    # Assert
    assert (response.status_code, response.json()) == (202, {"status": "queued"})


@pytest.mark.usefixtures("example_route")
async def test_the_request_enqueues_one_job(
    client: httpx.AsyncClient, queue: FakeQueue
) -> None:
    # Act
    await client.post("/api/v1/_example")

    # Assert
    assert [job.args for job in queue.named("example_job")] == [("+380000000001",)]
```

For a signed-in caller use `utils.auth` (`sign_up`, `sign_in`). Existing tests to imitate: `tests/unit/test_logging.py`, `tests/integration/db/test_db_account_models.py`,
`tests/integration/http/test_http_client.py`, `tests/integration/db/test_frozen_clock.py`. (They do not carry the AAA labels yet; POC-3.5 adds them. Until then follow this page, not their layout.)

## 5. Before you finish
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/integration`, `uv run pytest tests/e2e`: all
  green, and report the real output (rule B2).
- A bug fix starts with a test that fails for the right reason; show it failing, then passing (rule B5, `fix-bug` skill).
- Do not make a red test pass by loosening an assertion, skipping it, or re-running until green (rule B3).
