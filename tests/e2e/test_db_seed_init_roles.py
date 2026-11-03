"""The init.roles seed item on a real, migrated and unseeded database. Task: 5.1.

Each test has its own database (`unseeded_session_factory`), so none needs to delete a row to start empty (rule P6).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AccountRole, AccountRoleType, SeedHistory
from app.seeds.items.init_roles import InitRoles
from app.seeds.runner import run_seeds

type Factory = async_sessionmaker[AsyncSession]


async def role_types(factory: Factory) -> list[AccountRoleType]:
    async with factory() as session:
        rows = await session.scalars(select(AccountRole.type))
        # Sorted here: Postgres orders an enum by declaration, not by label.
        return sorted(rows)


async def history(factory: Factory) -> dict[str, tuple[bool, str | None]]:
    async with factory() as session:
        rows = await session.scalars(select(SeedHistory))
        return {row.name: (row.successful, row.result) for row in rows}


async def test_two_runs_create_each_role_once_and_one_successful_history_row(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles()])
    await run_seeds(unseeded_session_factory, [InitRoles()])

    assert await role_types(unseeded_session_factory) == [
        AccountRoleType.ADMIN,
        AccountRoleType.CUSTOMER,
    ]
    assert await history(unseeded_session_factory) == {"init.roles": (True, None)}


async def test_a_table_that_already_has_a_role_is_left_alone_and_leaves_no_history(
    unseeded_session_factory: Factory,
) -> None:
    async with unseeded_session_factory() as session, session.begin():
        session.add(AccountRole(type=AccountRoleType.ADMIN))

    await run_seeds(unseeded_session_factory, [InitRoles()])

    assert await role_types(unseeded_session_factory) == [AccountRoleType.ADMIN]
    assert await history(unseeded_session_factory) == {}


async def test_a_soft_deleted_role_still_counts_as_present(
    unseeded_session_factory: Factory,
) -> None:
    async with unseeded_session_factory() as session, session.begin():
        session.add(AccountRole(type=AccountRoleType.CUSTOMER, deleted=True))

    await run_seeds(unseeded_session_factory, [InitRoles()])

    assert await role_types(unseeded_session_factory) == [AccountRoleType.CUSTOMER]
