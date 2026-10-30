from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import get_settings


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
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
