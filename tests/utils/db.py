"""Where the database tests get their Postgres: an existing server, or a PostGIS container (ADR-0006)."""

from collections.abc import Callable

import pytest
from docker.errors import DockerException
from testcontainers.community.postgres import PostgresContainer

POSTGIS_IMAGE = "postgis/postgis:16-3.4"


def start_postgis() -> PostgresContainer:
    """Start the PostGIS container; the caller stops it. The URL it gives uses the asyncpg driver."""
    container = PostgresContainer(POSTGIS_IMAGE, driver="asyncpg")
    container.start()
    return container


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
