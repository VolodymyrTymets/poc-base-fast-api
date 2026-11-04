"""The whole seed list of an environment on a real, migrated and unseeded database. Task: 5.5."""

from typing import Literal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.models import Account, AccountRole, SeedHistory
from app.seeds.base import SeedError
from app.seeds.registry import seed_items
from app.seeds.runner import run_seeds

type Factory = async_sessionmaker[AsyncSession]


def settings_for(app_env: Literal["local", "production"]) -> Settings:
    return Settings(
        app_env=app_env,
        database_url=None,
        jwt_secret=ACCESS_KEY,
        jwt_refresh_token_secret=REFRESH_KEY,
    )


async def counts(factory: Factory) -> tuple[int, int, list[str]]:
    async with factory() as session:
        roles = await session.scalar(select(func.count()).select_from(AccountRole))
        accounts = await session.scalar(select(func.count()).select_from(Account))
        names = await session.scalars(select(SeedHistory.name).order_by("name"))
        return roles or 0, accounts or 0, list(names)


async def test_a_local_database_gets_two_roles_one_admin_and_three_customers(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, seed_items(settings_for("local")))

    assert await counts(unseeded_session_factory) == (
        2,
        4,
        ["init.admin", "init.customer", "init.roles"],
    )


async def test_a_second_boot_adds_nothing(unseeded_session_factory: Factory) -> None:
    for _ in range(2):
        await run_seeds(unseeded_session_factory, seed_items(settings_for("local")))

    assert await counts(unseeded_session_factory) == (
        2,
        4,
        ["init.admin", "init.customer", "init.roles"],
    )


async def test_production_gets_the_roles_and_no_account(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, seed_items(settings_for("production")))

    assert await counts(unseeded_session_factory) == (2, 0, ["init.roles"])


async def test_the_first_failing_item_stops_the_rest(
    unseeded_session_factory: Factory,
) -> None:
    # Without the roles the admin fails, and the customer item after it never runs.
    items = seed_items(settings_for("local"))[1:]

    with pytest.raises(SeedError, match="init.admin"):
        await run_seeds(unseeded_session_factory, items)

    assert await counts(unseeded_session_factory) == (0, 0, ["init.admin"])
