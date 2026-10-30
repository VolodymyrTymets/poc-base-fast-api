from collections.abc import AsyncIterator
from typing import Annotated
from unittest.mock import create_autospec

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import QueuePool

from app.config import Settings
from app.core.db import get_session
from app.main import create_app

Session = Annotated[AsyncSession, Depends(get_session)]


def client_for(app: FastAPI, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def connections_checked_out(app: FastAPI) -> int:
    """Connections the app's pool has handed out and not got back: 0 once every session is closed."""
    engine: AsyncEngine = app.state.engine
    assert isinstance(engine.pool, QueuePool)
    return engine.pool.checkedout()


def add_session_routes(
    app: FastAPI, seen: list[tuple[AsyncSession, bool]] | None = None
) -> None:
    # The app has no database route yet, so the test adds its own to this instance.
    @app.get("/api/v1/_select_one")
    async def select_one(session: Session) -> dict[str, int]:
        value = (await session.execute(text("SELECT 1"))).scalar_one()
        if seen is not None:
            seen.append((session, session.in_transaction()))
        return {"value": value}

    @app.post("/api/v1/_write_then_fail")
    async def write_then_fail(session: Session) -> None:
        await session.execute(
            text("INSERT INTO poc_session_rollback_probe (id) VALUES (1)")
        )
        raise RuntimeError("boom")


@pytest.fixture
async def app(database_url: str) -> AsyncIterator[FastAPI]:
    """The real app on the real database, with its lifespan running."""
    app = create_app(Settings(database_url=database_url))
    seen: list[tuple[AsyncSession, bool]] = []
    app.state.seen = seen
    add_session_routes(app, seen)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def probe_table(database_url: str) -> AsyncIterator[AsyncEngine]:
    """A real table, made and dropped through a second engine, so the test reads what was committed."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text("DROP TABLE IF EXISTS poc_session_rollback_probe")
        )
        await connection.execute(
            text("CREATE TABLE poc_session_rollback_probe (id integer)")
        )
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE poc_session_rollback_probe"))
    await engine.dispose()


async def test_a_session_runs_select_one(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.get("/api/v1/_select_one")

    assert (response.status_code, response.json()) == (200, {"value": 1})


async def test_each_request_gets_its_own_session_and_it_is_closed_after(
    app: FastAPI,
) -> None:
    async with client_for(app) as client:
        await client.get("/api/v1/_select_one")
        await client.get("/api/v1/_select_one")

    (first, first_open), (second, second_open) = app.state.seen
    assert first is not second
    assert (first_open, second_open) == (True, True)
    assert (first.in_transaction(), second.in_transaction()) == (False, False)
    assert connections_checked_out(app) == 0


async def test_a_failing_request_leaves_nothing_committed(
    app: FastAPI, probe_table: AsyncEngine
) -> None:
    async with client_for(app) as client:
        with pytest.raises(RuntimeError, match="boom"):
            await client.post("/api/v1/_write_then_fail")

    async with probe_table.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT count(*) FROM poc_session_rollback_probe")
            )
        ).scalar_one()
    assert rows == 0
    # The connection is back in the pool, so the session was closed and rolled back, not leaked.
    assert connections_checked_out(app) == 0


async def test_without_a_database_url_the_app_boots_and_health_answers() -> None:
    app = create_app(Settings())

    async with app.router.lifespan_context(app), client_for(app) as client:
        response = await client.get("/api/v1/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})


async def test_without_a_database_url_a_session_route_names_the_setting_in_the_error() -> (
    None
):
    app = create_app(Settings())
    add_session_routes(app)

    async with client_for(app) as client:
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            await client.get("/api/v1/_select_one")


async def test_without_a_database_url_the_client_gets_a_500_that_does_not_name_it() -> (
    None
):
    app = create_app(Settings())
    add_session_routes(app)

    async with client_for(app, raise_app_exceptions=False) as client:
        response = await client.get("/api/v1/_select_one")

    assert response.status_code == 500
    assert "DATABASE_URL" not in response.text


async def test_the_lifespan_disposes_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_autospec(AsyncEngine, instance=True)
    # Patched where app.main looks the name up; nothing connects to a database.
    monkeypatch.setattr("app.main.create_engine", lambda _settings: engine)
    app = create_app(Settings(database_url="postgresql+asyncpg://u:p@localhost/db"))

    async with app.router.lifespan_context(app):
        engine.dispose.assert_not_awaited()

    engine.dispose.assert_awaited_once()
