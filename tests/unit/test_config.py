from datetime import timedelta
from typing import Literal

import pytest
from pydantic import SecretStr, ValidationError

from app.config import DEFAULT_CORS_ORIGINS, Settings, get_settings, parse_duration

# Two different secrets of at least 32 characters.
GOOD_A = "a" * 32 + "-access"
GOOD_B = "b" * 32 + "-refresh"


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
    assert get_settings() is get_settings()


def test_rejects_an_unknown_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "nope")

    with pytest.raises(ValidationError, match="log_level"):
        Settings()


@pytest.mark.parametrize(
    ("name", "field"),
    [
        ("MAX_REQUEST_BODY_BYTES", "max_request_body_bytes"),
        ("SHUTDOWN_TIMEOUT_SECONDS", "shutdown_timeout_seconds"),
    ],
)
@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_rejects_a_limit_that_is_not_positive(
    monkeypatch: pytest.MonkeyPatch, name: str, field: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=field):
        Settings()


@pytest.mark.parametrize("value", [None, "", "  "], ids=["unset", "empty", "blank"])
def test_database_url_is_off_when_unset_or_blank(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is not None:
        monkeypatch.setenv("DATABASE_URL", value)

    assert Settings().database_url is None


def test_accepts_an_asyncpg_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql+asyncpg://u:p@localhost:5432/poc"
    monkeypatch.setenv("DATABASE_URL", url)

    assert Settings().database_url == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:secret@localhost/db",
        "mysql://u:secret@localhost/db",
        "secret",
    ],
    ids=["no-driver", "other-database", "not-a-url"],
)
def test_rejects_a_database_url_without_the_asyncpg_scheme_and_hides_it(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ValidationError, match="database_url") as error:
        Settings()

    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30s", timedelta(seconds=30)),
        ("15m", timedelta(minutes=15)),
        ("55min", timedelta(minutes=55)),
        ("2h", timedelta(hours=2)),
        ("7d", timedelta(days=7)),
        (" 7d ", timedelta(days=7)),
    ],
)
def test_parse_duration_reads_the_supported_units(
    raw: str, expected: timedelta
) -> None:
    assert parse_duration(raw) == expected


@pytest.mark.parametrize(
    "raw", ["15", "1w", "-5m", "0m", "", "m", "1.5h", "15 m", "15M"]
)
def test_parse_duration_rejects_everything_else(raw: str) -> None:
    with pytest.raises(ValueError, match="duration"):
        parse_duration(raw)


def test_jwt_defaults() -> None:
    settings = Settings()

    assert settings.jwt_access_token_expires_in == timedelta(minutes=15)
    assert settings.jwt_refresh_token_expires_in == timedelta(days=7)
    assert settings.jwt_secret is None
    assert settings.jwt_refresh_token_secret is None


def test_jwt_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "a")
    monkeypatch.setenv("JWT_REFRESH_TOKEN_SECRET", "b")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRES_IN", "55min")
    monkeypatch.setenv("JWT_REFRESH_TOKEN_EXPIRES_IN", "1d")

    settings = Settings()

    assert settings.jwt_secret is not None
    assert settings.jwt_secret.get_secret_value() == "a"
    assert settings.jwt_access_token_expires_in == timedelta(minutes=55)
    assert settings.jwt_refresh_token_expires_in == timedelta(days=1)


def test_a_blank_secret_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "  ")

    assert Settings().jwt_secret is None


@pytest.mark.parametrize(
    "name", ["JWT_ACCESS_TOKEN_EXPIRES_IN", "JWT_REFRESH_TOKEN_EXPIRES_IN"]
)
def test_a_bad_duration_stops_the_boot_and_names_the_field(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "soon")

    with pytest.raises(ValidationError, match=name.lower()):
        Settings()


def test_secrets_are_not_shown_in_repr() -> None:
    settings = Settings(
        jwt_secret=SecretStr(GOOD_A), jwt_refresh_token_secret=SecretStr(GOOD_B)
    )

    assert GOOD_A not in repr(settings)
    assert GOOD_B not in repr(settings)


@pytest.mark.parametrize("app_env", ["local", "test"])
def test_local_and_test_boot_without_secrets(app_env: Literal["local", "test"]) -> None:
    assert Settings(app_env=app_env).jwt_secret is None


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_strict_environments_accept_two_long_different_secrets(
    app_env: Literal["development", "production"],
) -> None:
    Settings(
        app_env=app_env,
        jwt_secret=SecretStr(GOOD_A),
        jwt_refresh_token_secret=SecretStr(GOOD_B),
    )


@pytest.mark.parametrize("app_env", ["development", "production"])
@pytest.mark.parametrize(
    ("access", "refresh", "message"),
    [
        (None, GOOD_B, "jwt_secret must be set"),
        (GOOD_A, None, "jwt_refresh_token_secret must be set"),
        ("short", GOOD_B, "jwt_secret must be at least 32"),
        (GOOD_A, "short", "jwt_refresh_token_secret must be at least 32"),
        (GOOD_A, GOOD_A, "must differ"),
    ],
    ids=["no-access", "no-refresh", "short-access", "short-refresh", "equal"],
)
def test_strict_environments_refuse_weak_or_missing_secrets(
    app_env: Literal["development", "production"],
    access: str | None,
    refresh: str | None,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message) as error:
        Settings(
            app_env=app_env,
            jwt_secret=None if access is None else SecretStr(access),
            jwt_refresh_token_secret=None if refresh is None else SecretStr(refresh),
        )

    # The message names fields, never a secret value.
    assert GOOD_A not in str(error.value)
    assert "short" not in str(error.value)
