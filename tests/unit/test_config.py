from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_CORS_ORIGINS, Settings, get_settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The env file is read from the working directory; an empty one keeps a
    # developer's real .env out of the tests.
    monkeypatch.chdir(tmp_path)
    for name in ("APP_ENV", "PORT", "CORS_ORIGINS"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_without_any_environment() -> None:
    settings = Settings()

    assert (settings.app_env, settings.port) == ("local", 3001)
    assert settings.cors_origins == list(DEFAULT_CORS_ORIGINS)


def test_reads_values_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PORT", "4000")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.port == 4000
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_a_blank_cors_origins_variable_means_the_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", " , ")

    assert Settings().cors_origins == list(DEFAULT_CORS_ORIGINS)


def test_rejects_a_port_that_is_not_a_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "abc")

    with pytest.raises(ValidationError, match="port"):
        Settings()


def test_rejects_an_unknown_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "nope")

    with pytest.raises(ValidationError, match="app_env"):
        Settings()


def test_get_settings_builds_the_settings_once() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()
