import pytest
from docker.errors import DockerException
from utils.db import resolve_server_url

CONTAINER_URL = "postgresql+asyncpg://test:test@localhost:5555/test"
ENV_URL = "postgresql+asyncpg://me:pw@db.example:5432/scratch"


def test_a_set_test_database_url_is_returned_and_no_container_is_started() -> None:
    started: list[str] = []

    def start() -> str:
        started.append("started")
        return CONTAINER_URL

    url = resolve_server_url(ENV_URL, start)

    assert (url, started) == (ENV_URL, [])


@pytest.mark.parametrize("env_url", [None, ""], ids=["unset", "blank"])
def test_without_a_test_database_url_the_container_url_is_returned(
    env_url: str | None,
) -> None:
    url = resolve_server_url(env_url, lambda: CONTAINER_URL)

    assert url == CONTAINER_URL


def test_a_docker_failure_fails_the_test_and_names_docker_and_the_setting() -> None:
    def start() -> str:
        raise DockerException("daemon not reachable")

    with pytest.raises(pytest.fail.Exception) as raised:
        resolve_server_url(None, start)

    message = str(raised.value)
    assert "Docker" in message
    assert "TEST_DATABASE_URL" in message
    assert "daemon not reachable" in message
