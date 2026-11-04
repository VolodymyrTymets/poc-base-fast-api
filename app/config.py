"""Settings read from the environment and validated once at boot. Tasks: 1.5."""

import re
from datetime import timedelta
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The local web apps (5173, 5174) that the Node base allowed. Ports move when a fork
# changes them, hence the CORS_ORIGINS override.
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://localhost:5174",
)


# ADR-0004: SQLAlchemy async with the asyncpg driver; any other scheme fails at boot.
DATABASE_URL_SCHEME = "postgresql+asyncpg://"


def parse_cors_origins(raw: str | None) -> list[str]:
    """Split a comma-separated list; an unset, empty or blank value means the defaults."""
    origins = [origin.strip() for origin in (raw or "").split(",") if origin.strip()]
    return origins or list(DEFAULT_CORS_ORIGINS)


DEFAULT_FILE_ALLOWED_MIME_TYPES = ("image/jpeg", "image/png")


def _normalise_mime_type(item: str) -> str:
    # The same rule FileAssertService applies to an upload: `image/PNG; charset=x` is `image/png`.
    media_type = item.split(";", 1)[0].strip().lower()
    if "/" not in media_type:
        # The message names the shape, never the value.
        raise ValueError("each mime type must look like type/subtype")
    return media_type


def _mime_types_from_env(value: str | list[str] | None) -> list[str]:
    # NoDecode hands the raw string over; a list (from code) is normalised the same way.
    items = value.split(",") if isinstance(value, str) else (value or [])
    return [_normalise_mime_type(item) for item in items if item.strip()]


def _cors_origins_from_env(value: str | list[str] | None) -> list[str]:
    # NoDecode hands the raw string over; a list (from code) is already parsed.
    if isinstance(value, list):
        return value
    return parse_cors_origins(value)


# ADR-0010: the token lifetimes keep the Node base's `15m` / `55min` / `7d` notation.
_DURATION_UNITS = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "min": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
}
_DURATION_PATTERN = re.compile(r"(\d+)(s|min|m|h|d)")

# Below this a HS256 key is guessable; only enforced outside local and test (task 4.4).
MIN_JWT_SECRET_LENGTH = 32
_STRICT_ENVS = {"development", "production"}


def parse_duration(raw: str) -> timedelta:
    """Read `30s`, `15m`, `55min`, `2h` or `7d`; anything else, and zero, is an error."""
    match = _DURATION_PATTERN.fullmatch(raw.strip())
    if match is None:
        raise ValueError("duration must look like 30s, 15m, 55min, 2h or 7d")
    duration = int(match.group(1)) * _DURATION_UNITS[match.group(2)]
    if duration <= timedelta(0):
        raise ValueError("duration must be greater than zero")
    return duration


def _duration_from_env(value: str | timedelta) -> timedelta:
    # A timedelta (from code) is already parsed.
    return parse_duration(value) if isinstance(value, str) else value


def _blank_to_none(value: str | None) -> str | None:
    # A blank SENTRY_DSN= line in .env means "off", the same as unset.
    return value.strip() or None if isinstance(value, str) else value


class Settings(BaseSettings):
    # extra="ignore": the env templates list variables that later tasks start reading.
    # hide_input_in_errors: DATABASE_URL carries a password, and a boot error goes to stderr
    # before logging is configured, so no rejected value may be echoed back.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["local", "development", "test", "production"] = "local"
    port: int = Field(default=3001, ge=1, le=65535)
    # 12 MiB: above FILE_MAX_SIZE (10 MB) plus multipart overhead; FileAssertService
    # (task 8.1) enforces the real upload limit.
    max_request_body_bytes: int = Field(default=12_582_912, gt=0)
    # How long SIGTERM lets in-flight requests finish before uvicorn cancels them.
    shutdown_timeout_seconds: int = Field(default=10, ge=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    sentry_dsn: Annotated[str | None, BeforeValidator(_blank_to_none)] = None
    # None means "no database": the app still boots, only a route that needs a session fails.
    database_url: Annotated[str | None, BeforeValidator(_blank_to_none)] = None
    # Tasks 4.4 and 7.x. Unset is allowed in local and test (the app boots, only issuing or
    # checking a token fails); development and production refuse to boot, see below.
    jwt_secret: Annotated[SecretStr | None, BeforeValidator(_blank_to_none)] = None
    jwt_refresh_token_secret: Annotated[
        SecretStr | None, BeforeValidator(_blank_to_none)
    ] = None
    jwt_access_token_expires_in: Annotated[
        timedelta, BeforeValidator(_duration_from_env)
    ] = timedelta(minutes=15)
    jwt_refresh_token_expires_in: Annotated[
        timedelta, BeforeValidator(_duration_from_env)
    ] = timedelta(days=7)
    cors_origins: Annotated[
        list[str], NoDecode, BeforeValidator(_cors_origins_from_env)
    ] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    # Task 8.1: the upload limits `FileAssertService` enforces. Bytes; the body limit above stays larger.
    file_max_size: int = Field(default=10_485_760, gt=0)
    # An unset variable means the defaults; one that is set but holds no type is refused, because an
    # empty allow-list would reject every upload without saying why.
    file_allowed_mime_types: Annotated[
        list[str], NoDecode, BeforeValidator(_mime_types_from_env), Field(min_length=1)
    ] = Field(default_factory=lambda: list(DEFAULT_FILE_ALLOWED_MIME_TYPES))

    # Task 6.1: where the arq queue lives. Only a connection is opened with these, and only on the first
    # enqueue or in the worker process, so the API boots with no Redis. The database index is a setting
    # because the tests run on index 15 and never touch a developer's own queue.
    redis_host: str = Field(default="localhost", min_length=1)
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_database: int = Field(default=0, ge=0, le=15)
    redis_password: Annotated[SecretStr | None, BeforeValidator(_blank_to_none)] = None

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg_scheme(cls, value: str | None) -> str | None:
        # The message names the field and the scheme, never the value (it holds a password).
        if value is not None and not value.startswith(DATABASE_URL_SCHEME):
            raise ValueError(f"database_url must start with {DATABASE_URL_SCHEME}")
        return value

    @model_validator(mode="after")
    def _require_strong_jwt_secrets(self) -> Self:
        if self.app_env not in _STRICT_ENVS:
            return self
        # Messages name the fields, never the values (they are secrets).
        problems: list[str] = []
        for name in ("jwt_secret", "jwt_refresh_token_secret"):
            secret: SecretStr | None = getattr(self, name)
            if secret is None:
                problems.append(f"{name} must be set")
            elif len(secret.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
                problems.append(
                    f"{name} must be at least {MIN_JWT_SECRET_LENGTH} characters"
                )
        if (
            self.jwt_secret is not None
            and self.jwt_refresh_token_secret is not None
            and self.jwt_secret.get_secret_value()
            == self.jwt_refresh_token_secret.get_secret_value()
        ):
            problems.append("jwt_secret and jwt_refresh_token_secret must differ")
        if problems:
            raise ValueError(f"{self.app_env}: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    """Build the settings once; a bad value stops the boot here, not on first use."""
    return Settings()
