"""Settings read from the environment and validated once at boot. Tasks: 1.5."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The local web apps (5173, 5174) that the Node base allowed. Ports move when a fork
# changes them, hence the CORS_ORIGINS override.
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://localhost:5174",
)


def parse_cors_origins(raw: str | None) -> list[str]:
    """Split a comma-separated list; an unset, empty or blank value means the defaults."""
    origins = [origin.strip() for origin in (raw or "").split(",") if origin.strip()]
    return origins or list(DEFAULT_CORS_ORIGINS)


def _cors_origins_from_env(value: str | list[str] | None) -> list[str]:
    # NoDecode hands the raw string over; a list (from code) is already parsed.
    if isinstance(value, list):
        return value
    return parse_cors_origins(value)


def _blank_to_none(value: str | None) -> str | None:
    # A blank SENTRY_DSN= line in .env means "off", the same as unset.
    return value.strip() or None if isinstance(value, str) else value


class Settings(BaseSettings):
    # extra="ignore": the env templates list variables that later tasks start reading.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "development", "test", "production"] = "local"
    port: int = Field(default=3001, ge=1, le=65535)
    # 12 MiB: above FILE_MAX_SIZE (10 MB) plus multipart overhead; the files module (8.x)
    # enforces the real upload limit.
    max_request_body_bytes: int = Field(default=12_582_912, gt=0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    sentry_dsn: Annotated[str | None, BeforeValidator(_blank_to_none)] = None
    cors_origins: Annotated[
        list[str], NoDecode, BeforeValidator(_cors_origins_from_env)
    ] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))


@lru_cache
def get_settings() -> Settings:
    """Build the settings once; a bad value stops the boot here, not on first use."""
    return Settings()
