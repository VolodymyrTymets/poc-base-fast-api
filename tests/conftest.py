from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from time_machine import TimeMachineFixture
from utils.client import running_client
from utils.clock import FROZEN_NOW
from utils.db import (
    build_template,
    create_database,
    database_url_for,
    drop_database,
    new_database_name,
    new_postgis,
    resolve_server_url,
)
from utils.queue import FakeQueue
from utils.redis import (
    TEST_REDIS_DATABASE,
    RedisTarget,
    new_redis,
    resolve_redis_target,
)

from app.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent


class DatabaseEnv(BaseSettings):
    # The environment wins over the file, as in app.config.Settings. The path is absolute
    # because the autouse fixture below runs every test from an empty temp directory.
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env.test", extra="ignore")

    test_database_url: str | None = None
    test_redis_url: str | None = None


@pytest.fixture(scope="session")
def redis_target() -> Iterator[RedisTarget]:
    """The Redis server the queue tests run against: `TEST_REDIS_URL`, else one container for the session."""
    stack = ExitStack()

    def start() -> RedisTarget:
        container = new_redis()
        stack.callback(container.stop)
        container.start()
        return RedisTarget(
            container.get_container_host_ip(),
            int(container.get_exposed_port(container.port)),
        )

    try:
        yield resolve_redis_target(DatabaseEnv().test_redis_url, start)
    finally:
        stack.close()


@pytest.fixture
async def redis_settings(redis_target: RedisTarget) -> AsyncIterator[Settings]:
    """Settings that point at the test Redis, index 15; that index is emptied before and after the test."""
    settings = Settings(
        redis_host=redis_target.host,
        redis_port=redis_target.port,
        redis_database=TEST_REDIS_DATABASE,
        redis_password=(
            SecretStr(redis_target.password) if redis_target.password else None
        ),
    )
    client = Redis(
        host=redis_target.host,
        port=redis_target.port,
        db=TEST_REDIS_DATABASE,
        password=redis_target.password,
    )
    try:
        await client.flushdb()
        yield settings
        await client.flushdb()
    finally:
        await client.aclose()


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
    """The name of a database migrated with `alembic upgrade head` and seeded, built once per session (ADR-0006).

    It is only ever copied, never written to by a test.
    """
    name = build_template(database_url, tmp_path_factory.mktemp("alembic"))
    try:
        yield name
    finally:
        drop_database(database_url, name)


@pytest.fixture(scope="session")
def unseeded_template_database(
    database_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[str]:
    """Like `template_database` but with no seed run: the starting point of the seed tests (task 5.1)."""
    name = build_template(
        database_url, tmp_path_factory.mktemp("alembic-unseeded"), seed=False
    )
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
def unseeded_database_url(
    database_url: str, unseeded_template_database: str
) -> Iterator[str]:
    """A migrated database that no seed has touched, one per test (the seed tests commit and may not delete rows, rule P6)."""
    name = new_database_name("unseeded")
    create_database(database_url, name, template=unseeded_template_database)
    try:
        yield database_url_for(database_url, name)
    finally:
        drop_database(database_url, name)


@pytest.fixture
async def unseeded_session_factory(
    unseeded_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(Settings(database_url=unseeded_database_url))
    assert engine is not None
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


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


@pytest.fixture
def frozen_clock(time_machine: TimeMachineFixture) -> TimeMachineFixture:
    """The process clock stopped at FROZEN_NOW; `frozen_clock.shift(timedelta(...))` moves it, nothing else does.

    For expiry tests: shift past the limit instead of sleeping. It moves this process only, so a database default such as
    CURRENT_TIMESTAMP still reads the server's clock; services pass `utc_now()` themselves. It does not touch
    `time.monotonic`, so the event loop and the database drivers keep real time.
    """
    time_machine.move_to(FROZEN_NOW, tick=False)
    return time_machine


@pytest.fixture
def queue() -> FakeQueue:
    """A fresh queue that records enqueued jobs; pass it to the code under test where the real queue goes."""
    return FakeQueue()


@pytest.fixture
def asgi_app(module_database_url: str) -> FastAPI:
    """The real app from `create_app`, on this module's database. Routes a test adds to it live for that test only."""
    return create_app(Settings(database_url=module_database_url))


@pytest.fixture
async def client(asgi_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client on `asgi_app`, with the lifespan started before the test and stopped after it.

    It needs a database (Docker or TEST_DATABASE_URL). A test without one uses
    `running_client(create_app(Settings()))` directly.
    """
    async with running_client(asgi_app) as http_client:
        yield http_client


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
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_DATABASE",
        "REDIS_PASSWORD",
        "JWT_SECRET",
        "JWT_REFRESH_TOKEN_SECRET",
        "JWT_ACCESS_TOKEN_EXPIRES_IN",
        "JWT_REFRESH_TOKEN_EXPIRES_IN",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
