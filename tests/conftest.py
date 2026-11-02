from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict
from utils.db import resolve_server_url, start_postgis

from app.config import get_settings

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
        container = start_postgis()
        stack.callback(container.stop)
        return container.get_connection_url()

    try:
        yield resolve_server_url(DatabaseEnv().test_database_url, start)
    finally:
        stack.close()


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
