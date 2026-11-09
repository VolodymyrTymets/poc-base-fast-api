"""The container image: its two targets built and run, as `docker run` runs them. Task: POC-11.1 (ADR-0030).

Every test goes through a database fixture, so they carry the `db` marker and `-m "not db and not redis"` never selects them.
The image runs in a container, which reaches the test Postgres through `host.docker.internal` (the `host-gateway` entry makes
that name work on Linux as well as Docker Desktop). A missing Docker daemon fails the test with a message, never a skip.
"""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import docker
import httpx
import pytest
from docker import DockerClient
from docker.errors import DockerException
from docker.models.containers import Container
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer
from utils.db import (
    create_database,
    database_url_for,
    drop_database,
    new_database_name,
)

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_REPOSITORY = "poc-base-image-test"
HOST_ALIAS = "host.docker.internal"
CONTAINER_PORT = "3001/tcp"
WAIT_SECONDS = 90.0
# The first line arq logs when it starts; the tests wait for it, not for a fixed time.
WORKER_STARTED = "Starting worker for"


LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def container_host(host: str) -> str:
    """The host a container reaches: a loopback address inside it is the container itself, so it becomes the host's alias.

    Any other host (a `TEST_*_URL` pointing at a shared server) is reachable as it is.
    """
    return HOST_ALIAS if host in LOOPBACK else host


def for_container(url: str) -> str:
    """The same URL with a host a container can reach."""
    parsed = make_url(url)
    return parsed.set(host=container_host(parsed.host or "")).render_as_string(
        hide_password=False
    )


def wait_until(
    condition: Callable[[], bool],
    what: str,
    evidence: Callable[[], str] = lambda: "",
) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail(
                f"gave up waiting for {what} after {WAIT_SECONDS:.0f} s\n{evidence()}"
            )
        time.sleep(0.5)


@pytest.fixture(scope="module")
def docker_client(database_url: str) -> DockerClient:
    # `database_url` first: its failure message names Docker when the daemon is down, and it is what marks these tests `db`.
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as error:
        pytest.fail(f"the image tests need a Docker daemon: {error}", pytrace=False)
    return client


@pytest.fixture(scope="module")
def images(docker_client: DockerClient) -> dict[str, str]:
    tags = {}
    for target in ("development", "worker"):
        tag = f"{IMAGE_REPOSITORY}:{target}"
        docker_client.images.build(path=str(REPO_ROOT), target=target, tag=tag, rm=True)
        tags[target] = tag
    return tags


@pytest.fixture
def run_container(docker_client: DockerClient) -> Iterator[Callable[..., Container]]:
    started: list[Container] = []

    def run(image: str, **options: Any) -> Container:
        container = docker_client.containers.run(
            image,
            detach=True,
            extra_hosts={HOST_ALIAS: "host-gateway"},
            **options,
        )
        started.append(container)
        return container

    yield run
    for container in started:
        container.remove(force=True)


def empty_database_url(server_url: str) -> Iterator[str]:
    """A database with nothing in it, not even the schema: the container has to build it. Yields the host-side URL."""
    name = new_database_name("image")
    create_database(server_url, name)
    yield database_url_for(server_url, name)
    drop_database(server_url, name)


@pytest.fixture
def empty_database(database_url: str) -> Iterator[str]:
    """One empty database for one test; a container that migrates it does not change what the next test starts from."""
    yield from empty_database_url(database_url)


@pytest.fixture(scope="module")
def api_database(database_url: str) -> Iterator[str]:
    """The database of `running_api`, shared by the tests that look at what that one container did to it."""
    yield from empty_database_url(database_url)


def health_port(container: Container) -> int:
    bindings: list[dict[str, str]] = []

    def published() -> bool:
        container.reload()
        bindings[:] = container.ports.get(CONTAINER_PORT) or []
        return bool(bindings)

    wait_until(published, "the published port", lambda: container.logs().decode())
    return int(bindings[0]["HostPort"])


def wait_for_health(port: int, container: Container) -> httpx.Response:
    def answers() -> bool:
        try:
            return (
                httpx.get(f"http://127.0.0.1:{port}/api/v1/health").status_code == 200
            )
        except httpx.TransportError:
            return False

    wait_until(answers, "GET /api/v1/health", lambda: container.logs().decode())
    return httpx.get(f"http://127.0.0.1:{port}/api/v1/health")


@pytest.fixture(scope="module")
def running_api(
    images: dict[str, str],
    api_database: str,
    docker_client: DockerClient,
) -> Iterator[Container]:
    container = docker_client.containers.run(
        images["development"],
        detach=True,
        extra_hosts={HOST_ALIAS: "host-gateway"},
        environment={"DATABASE_URL": for_container(api_database)},
        ports={CONTAINER_PORT: None},
    )
    try:
        wait_for_health(health_port(container), container)
        yield container
    finally:
        container.remove(force=True)


def test_the_development_image_serves_health_after_it_migrated(
    running_api: Container,
) -> None:
    # Arrange
    port = health_port(running_api)

    # Act
    response = httpx.get(f"http://127.0.0.1:{port}/api/v1/health")

    # Assert
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


async def test_the_development_image_seeded_the_two_roles(
    running_api: Container, api_database: str
) -> None:
    # Arrange
    engine = create_async_engine(api_database)

    # Act
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text('SELECT type::text FROM "AccountRole"')
            )
            roles = sorted(rows.scalars().all())
    finally:
        await engine.dispose()

    # Assert
    assert roles == ["ADMIN", "CUSTOMER"]


def test_the_development_image_runs_as_a_non_root_user(running_api: Container) -> None:
    # Arrange / Act
    user = running_api.attrs["Config"]["User"]

    # Assert
    assert user == "app"


def test_a_stopped_api_container_exits_cleanly_without_being_killed(
    images: dict[str, str],
    empty_database: str,
    run_container: Callable[..., Container],
) -> None:
    # Arrange: SIGTERM only reaches the server because the entrypoint ends in `exec`.
    container = run_container(
        images["development"],
        environment={"DATABASE_URL": for_container(empty_database)},
        ports={CONTAINER_PORT: None},
    )
    wait_for_health(health_port(container), container)

    # Act
    container.stop(timeout=10)
    container.reload()

    # Assert: 137 would mean the 10 s grace ran out and Docker sent SIGKILL. 0 is the status of a server that is PID 1
    # (the kernel drops the signal uvicorn re-raises); 143 is the one an init process such as `docker run --init` passes on.
    assert container.attrs["State"]["ExitCode"] in (0, 143)


def test_a_failing_migration_stops_the_container_before_the_server_starts(
    images: dict[str, str],
    database_url: str,
    run_container: Callable[..., Container],
) -> None:
    # Arrange: a Postgres without the PostGIS files cannot run `CREATE EXTENSION postgis`, the first revision.
    with PostgresContainer("postgres:16", driver="asyncpg") as plain:
        url = for_container(plain.get_connection_url())

        # Act
        container = run_container(
            images["development"], environment={"DATABASE_URL": url}
        )
        outcome = container.wait(timeout=int(WAIT_SECONDS))
        logs = container.logs().decode()

    # Assert
    assert outcome["StatusCode"] != 0
    assert 'extension "postgis" is not available' in logs
    assert "Uvicorn running" not in logs


def test_the_image_holds_no_env_file_at_any_depth_and_no_secret_setting(
    images: dict[str, str],
    docker_client: DockerClient,
) -> None:
    # Arrange
    listing = docker_client.containers.run(
        images["development"],
        entrypoint="sh",
        # Any .env file at any depth, the examples aside: `.dockerignore` must not let one in under app/ or tests/.
        command=[
            "-c",
            "find /app -name '.env*' ! -name '*.example' -not -path '/app/.venv/*'",
        ],
        remove=True,
    ).decode()
    env_names = [
        entry.split("=", 1)[0]
        for entry in docker_client.images.get(images["development"]).attrs["Config"][
            "Env"
        ]
    ]

    # Act
    leaked = [
        name
        for name in env_names
        if name.startswith(("DATABASE_URL", "JWT_", "SENTRY_", "REDIS_"))
    ]

    # Assert
    assert (listing.split(), leaked) == ([], [])


@pytest.fixture
def running_worker(
    images: dict[str, str],
    empty_database: str,
    redis_settings: Settings,
    run_container: Callable[..., Container],
) -> Container:
    # `redis_settings` points at index 15 only, the one index the tests touch and flush, so a developer's own queue is left alone.
    password = redis_settings.redis_password
    container = run_container(
        images["worker"],
        environment={
            "DATABASE_URL": for_container(empty_database),
            "REDIS_HOST": container_host(redis_settings.redis_host),
            "REDIS_PORT": str(redis_settings.redis_port),
            "REDIS_DATABASE": str(redis_settings.redis_database),
            **({"REDIS_PASSWORD": password.get_secret_value()} if password else {}),
        },
    )
    wait_until(
        lambda: WORKER_STARTED in container.logs().decode(),
        "the worker start-up line",
        lambda: container.logs().decode(),
    )
    return container


def test_the_worker_image_starts_the_arq_worker(running_worker: Container) -> None:
    # Arrange / Act
    logs = running_worker.logs().decode()

    # Assert
    assert f"{WORKER_STARTED} 3 functions" in logs


async def test_the_worker_image_does_not_migrate_or_seed(
    running_worker: Container, empty_database: str
) -> None:
    # Arrange
    engine = create_async_engine(empty_database)

    # Act
    try:
        async with engine.connect() as connection:
            table = (
                await connection.execute(text("SELECT to_regclass('\"Account\"')"))
            ).scalar_one()
    finally:
        await engine.dispose()

    # Assert
    assert table is None
