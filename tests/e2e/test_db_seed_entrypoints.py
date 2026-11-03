"""The two ways the seeds start: the app's lifespan and `python -m app.seeds`. Task: 5.1.

Both run on a real, migrated and unseeded database (`unseeded_database_url`).
"""

import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from utils.client import client_for

from app.config import Settings
from app.main import create_app
from app.seeds.base import SeedItem


class BrokenItem:
    name = "broken"

    async def needs_to_run(self, session: object) -> bool:
        return True

    async def run(self, session: object) -> None:
        raise RuntimeError("seed exploded")


async def values(database_url: str, sql: str) -> list[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return sorted((await connection.execute(text(sql))).scalars().all())
    finally:
        await engine.dispose()


def run_module(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # The autouse fixture clears the app's variables and runs from an empty directory, so a developer's .env is not read.
    return subprocess.run(
        [sys.executable, "-I", "-m", "app.seeds"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


ROLES_SQL = 'SELECT type::text FROM "AccountRole"'
HISTORY_SQL = "SELECT name || ':' || successful::text FROM \"SeedHistory\""


async def test_starting_the_app_seeds_the_roles_and_a_second_start_adds_nothing(
    unseeded_database_url: str,
) -> None:
    for _ in range(2):
        app = create_app(Settings(database_url=unseeded_database_url))
        async with app.router.lifespan_context(app), client_for(app) as client:
            response = await client.get("/api/v1/health")
        assert response.status_code == 200

    assert await values(unseeded_database_url, ROLES_SQL) == ["ADMIN", "CUSTOMER"]
    assert await values(unseeded_database_url, HISTORY_SQL) == ["init.roles:true"]


async def test_a_failing_seed_stops_the_boot_and_is_recorded(
    unseeded_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_settings: Settings) -> list[SeedItem]:
        return [BrokenItem()]

    monkeypatch.setattr("app.main.seed_items", broken)
    app = create_app(Settings(database_url=unseeded_database_url))

    with pytest.raises(
        Exception, match="seed broken failed: RuntimeError: seed exploded"
    ):
        async with app.router.lifespan_context(app):
            pytest.fail("the app must not start serving")

    assert await values(unseeded_database_url, HISTORY_SQL) == ["broken:false"]


async def test_the_app_without_a_database_url_boots_and_seeds_nothing() -> None:
    app = create_app(Settings())

    async with app.router.lifespan_context(app), client_for(app) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200


async def test_the_command_seeds_and_exits_0_twice(unseeded_database_url: str) -> None:
    env = {"DATABASE_URL": unseeded_database_url, "APP_ENV": "test", "PATH": "/usr/bin"}

    first = run_module(env)
    second = run_module(env)

    assert (first.returncode, second.returncode) == (0, 0), first.stderr + second.stderr
    assert await values(unseeded_database_url, ROLES_SQL) == ["ADMIN", "CUSTOMER"]
    assert await values(unseeded_database_url, HISTORY_SQL) == ["init.roles:true"]


def test_the_command_without_a_database_url_exits_1_and_names_the_setting() -> None:
    result = run_module({"APP_ENV": "test", "PATH": "/usr/bin"})

    assert (result.returncode, "DATABASE_URL" in result.stderr) == (1, True)
