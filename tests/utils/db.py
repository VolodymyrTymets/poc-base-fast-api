"""Where the database tests get their Postgres: an existing server, or a PostGIS container (ADR-0006).

Also the template database: built once per session with `alembic upgrade head`, copied for each test module.
The functions here are synchronous on purpose: they run from session and module fixtures, outside any event
loop, and env.py of Alembic calls `asyncio.run` itself.
"""

import asyncio
import re
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from docker.errors import DockerException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from app.config import get_settings

POSTGIS_IMAGE = "postgis/postgis:16-3.4"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Every database this module creates starts with this prefix, and it is the only kind it ever drops.
DATABASE_PREFIX = "poc_test_"
_OWN_DATABASE = re.compile(rf"^{DATABASE_PREFIX}[a-z0-9_]+$")


def new_postgis() -> PostgresContainer:
    """A PostGIS container, not started. The caller registers `stop` first and then calls `start`,
    so a container whose start times out is still stopped. Its URL uses the asyncpg driver."""
    return PostgresContainer(POSTGIS_IMAGE, driver="asyncpg")


def resolve_server_url(env_url: str | None, start: Callable[[], str]) -> str:
    """The server URL the suite uses: `TEST_DATABASE_URL` if set, else whatever `start` brings up.

    A Docker failure is a test failure, not a skip: a skipped database test would pass without proving anything.
    """
    if env_url:
        return env_url
    try:
        return start()
    except DockerException as error:
        pytest.fail(
            f"no Postgres for the database tests: Docker is not available ({error}); "
            "start Docker, or set TEST_DATABASE_URL in .env.test or the environment "
            "(see docs/RUNBOOK.md)",
            pytrace=False,
        )


def new_database_name(kind: str) -> str:
    """A name this module may later drop; generated here, never taken from input."""
    return f"{DATABASE_PREFIX}{kind}_{uuid.uuid4().hex[:8]}"


def database_url_for(server_url: str, name: str) -> str:
    """The URL of database `name` on the server `server_url` points at."""
    return make_url(server_url).set(database=name).render_as_string(hide_password=False)


def _run_on_server(server_url: str, statement: str) -> None:
    async def run() -> None:
        # AUTOCOMMIT: CREATE and DROP DATABASE cannot run inside a transaction.
        engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                await connection.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(run())


def _require_own(name: str) -> str:
    if not _OWN_DATABASE.fullmatch(name):
        raise ValueError(
            f"{name!r} is not a database of this test suite (expected {DATABASE_PREFIX}...)"
        )
    return name


def create_database(server_url: str, name: str, template: str | None = None) -> None:
    """Create database `name`, optionally copied from `template` (which must have no open connection)."""
    suffix = f' TEMPLATE "{_require_own(template)}"' if template else ""
    _run_on_server(server_url, f'CREATE DATABASE "{_require_own(name)}"{suffix}')


def drop_database(server_url: str, name: str) -> None:
    """Drop a database this module created; any other name is refused before a statement is sent."""
    _run_on_server(
        server_url, f'DROP DATABASE IF EXISTS "{_require_own(name)}" WITH (FORCE)'
    )


async def commit_marker_account(engine: AsyncEngine, marker: str) -> list[str]:
    """Commit one Account with id `marker`, then return the ids of every Account in that database."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                'INSERT INTO "Account" (id, "lastLoginAt", "updatedAt") '
                "VALUES (:id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": marker},
        )
    async with engine.connect() as connection:
        rows = await connection.execute(text('SELECT id FROM "Account" ORDER BY id'))
        return list(rows.scalars().all())


def build_template(server_url: str, workdir: Path) -> str:
    """Create a database and bring it to `alembic upgrade head`; returns its name.

    The environment is isolated for the call only: DATABASE_URL points at the new database, and the working
    directory is `workdir`, so a developer's own .env is not read.
    """
    name = new_database_name("template")
    create_database(server_url, name)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("DATABASE_URL", database_url_for(server_url, name))
            patch.chdir(workdir)
            get_settings.cache_clear()
            try:
                command.upgrade(Config(str(REPO_ROOT / "alembic.ini")), "head")
            finally:
                get_settings.cache_clear()
    except BaseException:
        # A half-built template must not stay on a server we do not own; the error still propagates.
        drop_database(server_url, name)
        raise
    return name
