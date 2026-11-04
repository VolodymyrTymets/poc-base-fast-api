"""Where the queue tests get their Redis: an existing server, or a container (task 6.1; mirrors tests/utils/db.py).

The tests only ever use database index 15 of that server and flush only that index, never the whole server, so
pointing `TEST_REDIS_URL` at a developer's own Redis leaves the default database (and its queue) alone.
"""

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import pytest
from docker.errors import DockerException
from testcontainers.community.redis import RedisContainer

REDIS_IMAGE = "redis:7-alpine"
# The one Redis index the tests touch; the default, 0, may be the one a developer's own worker uses.
TEST_REDIS_DATABASE = 15


@dataclass(frozen=True)
class RedisTarget:
    host: str
    port: int
    password: str | None = None


def new_redis() -> RedisContainer:
    """A Redis container, not started (the caller registers `stop` first, as with the Postgres one)."""
    return RedisContainer(REDIS_IMAGE)


def target_from_url(url: str) -> RedisTarget:
    """`redis://[:password@]host[:port][/index]`; the index part is ignored, the tests use 15."""
    parts = urlsplit(url)
    if parts.scheme != "redis" or not parts.hostname:
        raise ValueError("TEST_REDIS_URL must look like redis://host:port")
    return RedisTarget(parts.hostname, parts.port or 6379, parts.password)


def resolve_redis_target(
    env_url: str | None, start: Callable[[], RedisTarget]
) -> RedisTarget:
    """`TEST_REDIS_URL` if set, else whatever `start` brings up. A Docker failure fails the test, never skips it."""
    if env_url:
        return target_from_url(env_url)
    try:
        return start()
    except DockerException as error:
        pytest.fail(
            f"no Redis for the queue tests: Docker is not available ({error}); "
            "start Docker, or set TEST_REDIS_URL in .env.test or the environment "
            "(see docs/RUNBOOK.md)",
            pytrace=False,
        )
