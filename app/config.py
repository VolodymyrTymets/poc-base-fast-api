"""Settings read from the environment and validated once at boot. Tasks: 1.5."""

from functools import lru_cache
from typing import Annotated, Any, Literal

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


def _cors_origins_from_env(value: Any) -> Any:
    # NoDecode hands the raw string over; a list (from code) is already parsed.
    if value is None or isinstance(value, str):
        return parse_cors_origins(value)
    return value


class Settings(BaseSettings):
    # extra="ignore": the env templates list variables that later tasks start reading.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "development", "test", "production"] = "local"
    port: int = Field(default=3001, ge=1, le=65535)
    cors_origins: Annotated[
        list[str], NoDecode, BeforeValidator(_cors_origins_from_env)
    ] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))


@lru_cache
def get_settings() -> Settings:
    """Build the settings once; a bad value stops the boot here, not on first use."""
    return Settings()
