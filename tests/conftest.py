from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from utils.db import (
    build_template,
    create_database,
    database_url_for,
    drop_database,
    new_database_name,
    new_postgis,
    resolve_server_url,
)

from app.config import Settings, get_settings
from app.core.db import create_engine

REPO_ROOT = Path(__file__).resolve().parent.parent


class DatabaseEnv(BaseSettings):
    # The environment wins over the file, as in app.config.Settings. The path is absolute
    # because the autouse fixture below runs every test from an empty temp directory.
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env.test", extra="ignore")

    test_database_url: str | None = None


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """The URL of the real Postgres server the database tests run against (rule P8).

    `TEST_DATABASE_URL` wins; without it one PostGIS container lives for the whole session (ADR-0006).
    """
    stack = ExitStack()

    def start() -> str:
        container = new_postgis()
        stack.callback(container.stop)
        container.start()
        return container.get_connection_url()

    try:
        yield resolve_server_url(DatabaseEnv().test_database_url, start)
    finally:
        stack.close()


@pytest.fixture(scope="session")
def template_database(
    database_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[str]:
    """The name of a database migrated with `alembic upgrade head`, built once per session (ADR-0006).

    Seeds join it in task 5.1. It is only ever copied, never written to by a test.
    """
    name = build_template(database_url, tmp_path_factory.mktemp("alembic"))
    try:
        yield name
    finally:
        drop_database(database_url, name)


@pytest.fixture(scope="module")
def module_database_url(database_url: str, template_database: str) -> Iterator[str]:
    """The URL of a database of this test module's own: a copy of the template, dropped after the module."""
    name = new_database_name("module")
    create_database(database_url, name, template=template_database)
    try:
        yield database_url_for(database_url, name)
    finally:
        drop_database(database_url, name)


@pytest.fixture
async def db_engine(module_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The app's engine on the module's database. What a test commits through it stays for the module."""
    engine = create_engine(Settings(database_url=module_database_url))
    assert engine is not None
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back when the test ends, commits included.

    The outer transaction belongs to the connection; the session's own commit only releases a SAVEPOINT.
    """
    async with db_engine.connect() as connection:
        outer = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture(autouse=True)
def isolated_settings_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    # Settings read variables from the process and a .env in the working directory; an
    # empty directory and cleared variables keep a developer's own setup out of every test.
    monkeypatch.chdir(tmp_path)
    for name in (
        "APP_ENV",
        "PORT",
        "CORS_ORIGINS",
        "LOG_LEVEL",
        "SENTRY_DSN",
        "MAX_REQUEST_BODY_BYTES",
        "SHUTDOWN_TIMEOUT_SECONDS",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
