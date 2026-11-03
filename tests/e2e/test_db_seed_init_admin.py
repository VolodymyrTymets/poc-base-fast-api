"""The init.admin seed item on a real, migrated and unseeded database. Task: 5.5.

Each test has its own database (`unseeded_session_factory`), so none needs to delete a row to start empty (rule P6).
"""

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.db import utc_now
from app.models import (
    Account,
    AccountOnRole,
    AccountProfile,
    AccountRoleType,
    SeedHistory,
)
from app.seeds.base import SeedError
from app.seeds.items.init_admin import (
    ADMINS,
    InitAdmin,
    SampleAdminPhoneInUseError,
)
from app.seeds.items.init_roles import InitRoles
from app.seeds.runner import run_seeds
from app.services.account import AccountService
from app.services.account_role import AccountRoleService

type Factory = async_sessionmaker[AsyncSession]

SETTINGS = Settings(database_url=None)


async def admin_roles(factory: Factory) -> dict[str, list[AccountRoleType]]:
    """The roles of every account, by profile phone number."""
    async with factory() as session:
        rows = await session.execute(
            select(Account.id, AccountProfile.phone_number).join(
                AccountProfile, AccountProfile.account_id == Account.id
            )
        )
        service = AccountRoleService(session)
        return {
            str(phone): await service.get_account_roles(account_id)
            for account_id, phone in rows.all()
        }


async def history(factory: Factory) -> dict[str, tuple[bool, str | None]]:
    async with factory() as session:
        rows = await session.scalars(select(SeedHistory))
        return {row.name: (row.successful, row.result) for row in rows}


async def test_the_admin_holds_the_admin_role_only(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles(), InitAdmin(SETTINGS)])

    assert await admin_roles(unseeded_session_factory) == {
        ADMINS[0]["phone_number"]: [AccountRoleType.ADMIN]
    }


async def test_the_admin_profile_has_the_sample_names(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles(), InitAdmin(SETTINGS)])

    async with unseeded_session_factory() as session:
        profile = (await session.scalars(select(AccountProfile))).one()
    assert (profile.first_name, profile.last_name, profile.phone_number) == (
        ADMINS[0]["first_name"],
        ADMINS[0]["last_name"],
        ADMINS[0]["phone_number"],
    )


async def test_two_runs_create_one_admin_and_one_history_row(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles(), InitAdmin(SETTINGS)])
    await run_seeds(unseeded_session_factory, [InitRoles(), InitAdmin(SETTINGS)])

    assert len(await admin_roles(unseeded_session_factory)) == 1
    assert await history(unseeded_session_factory) == {
        "init.roles": (True, None),
        "init.admin": (True, None),
    }


async def test_another_admin_already_present_leaves_the_database_alone(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles()])
    async with unseeded_session_factory() as session, session.begin():
        other = Account(last_login_at=utc_now())
        session.add(other)
        await session.flush()
        await AccountRoleService(session).add_account_to_role(
            other.id, AccountRoleType.ADMIN
        )

    await run_seeds(unseeded_session_factory, [InitAdmin(SETTINGS)])

    async with unseeded_session_factory() as session:
        accounts = len((await session.scalars(select(Account.id))).all())
    assert accounts == 1
    assert "init.admin" not in await history(unseeded_session_factory)


async def test_without_the_roles_the_item_fails_and_is_recorded(
    unseeded_session_factory: Factory,
) -> None:
    with pytest.raises(SeedError, match="init.admin"):
        await run_seeds(unseeded_session_factory, [InitAdmin(SETTINGS)])

    recorded = await history(unseeded_session_factory)
    assert recorded["init.admin"][0] is False
    assert "RoleNotFoundError" in str(recorded["init.admin"][1])
    async with unseeded_session_factory() as session:
        assert (await session.scalars(select(Account.id))).all() == []


async def make_admin(factory: Factory) -> str:
    async with factory() as session, session.begin():
        other = Account(last_login_at=utc_now())
        session.add(other)
        await session.flush()
        await AccountRoleService(session).add_account_to_role(
            other.id, AccountRoleType.ADMIN
        )
        return other.id


async def test_an_admin_whose_role_link_is_soft_deleted_does_not_count(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles()])
    old = await make_admin(unseeded_session_factory)
    async with unseeded_session_factory() as session, session.begin():
        await session.execute(
            update(AccountOnRole)
            .where(AccountOnRole.account_id == old)
            .values(deleted=True)
        )

    await run_seeds(unseeded_session_factory, [InitAdmin(SETTINGS)])

    assert ADMINS[0]["phone_number"] in await admin_roles(unseeded_session_factory)


async def test_an_admin_whose_account_is_soft_deleted_does_not_count(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles()])
    old = await make_admin(unseeded_session_factory)
    async with unseeded_session_factory() as session, session.begin():
        await session.execute(
            update(Account).where(Account.id == old).values(deleted=True)
        )

    await run_seeds(unseeded_session_factory, [InitAdmin(SETTINGS)])

    assert ADMINS[0]["phone_number"] in await admin_roles(unseeded_session_factory)


async def test_a_sample_admin_phone_that_has_an_account_fails_the_item_clearly(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles()])
    async with unseeded_session_factory() as session, session.begin():
        await AccountService(session).create_customer(ADMINS[0]["phone_number"])

    with pytest.raises(SeedError, match="init.admin"):
        await run_seeds(unseeded_session_factory, [InitAdmin(SETTINGS)])

    recorded = await history(unseeded_session_factory)
    assert recorded["init.admin"][0] is False
    assert SampleAdminPhoneInUseError.__name__ in str(recorded["init.admin"][1])
