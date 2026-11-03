"""The init.customer seed item on a real, migrated and unseeded database. Task: 5.5.

Each test has its own database (`unseeded_session_factory`), so none needs to delete a row to start empty (rule P6).
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import AccountProfile, AccountRoleType, SeedHistory
from app.seeds.base import SeedError, SeedItem
from app.seeds.items.init_admin import InitAdmin
from app.seeds.items.init_customer import CUSTOMERS, InitCustomer
from app.seeds.items.init_roles import InitRoles
from app.seeds.runner import run_seeds
from app.services.account import AccountService
from app.services.account_role import AccountRoleService

type Factory = async_sessionmaker[AsyncSession]

SETTINGS = Settings(database_url=None)
FIRST = CUSTOMERS[0]


async def profiles_by_phone(factory: Factory) -> dict[str, AccountProfile]:
    async with factory() as session:
        rows = await session.scalars(select(AccountProfile))
        return {str(row.phone_number): row for row in rows}


async def roles_of(factory: Factory, phone: str) -> list[AccountRoleType]:
    async with factory() as session:
        account = await AccountService(session).get_by_phone(phone)
        assert account is not None
        return await AccountRoleService(session).get_account_roles(account.id)


async def history(factory: Factory) -> dict[str, tuple[bool, str | None]]:
    async with factory() as session:
        rows = await session.scalars(select(SeedHistory))
        return {row.name: (row.successful, row.result) for row in rows}


async def test_each_customer_has_the_sample_profile_and_the_customer_role_only(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles(), InitCustomer(SETTINGS)])

    profiles = await profiles_by_phone(unseeded_session_factory)
    assert {
        phone: (p.email, p.first_name, p.last_name, p.middle_name, p.date_of_birth)
        for phone, p in profiles.items()
    } == {
        sample["phone_number"]: (
            sample["email"],
            sample["first_name"],
            sample["last_name"],
            sample["middle_name"],
            sample["date_of_birth"],
        )
        for sample in CUSTOMERS
    }
    for sample in CUSTOMERS:
        assert await roles_of(unseeded_session_factory, sample["phone_number"]) == [
            AccountRoleType.CUSTOMER
        ]


async def test_the_customers_are_created_although_an_admin_already_exists(
    unseeded_session_factory: Factory,
) -> None:
    # Node's `account.count() === 0` check made the customers a no-op once the admin existed.
    await run_seeds(
        unseeded_session_factory,
        [InitRoles(), InitAdmin(SETTINGS), InitCustomer(SETTINGS)],
    )

    assert len(await profiles_by_phone(unseeded_session_factory)) == 1 + len(CUSTOMERS)


async def test_two_runs_add_nothing_and_leave_one_history_row(
    unseeded_session_factory: Factory,
) -> None:
    items: list[SeedItem] = [InitRoles(), InitCustomer(SETTINGS)]
    await run_seeds(unseeded_session_factory, items)
    await run_seeds(unseeded_session_factory, items)

    assert len(await profiles_by_phone(unseeded_session_factory)) == len(CUSTOMERS)
    assert await history(unseeded_session_factory) == {
        "init.roles": (True, None),
        "init.customer": (True, None),
    }


async def test_a_customer_that_already_exists_is_not_duplicated_and_the_others_are_created(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles()])
    async with unseeded_session_factory() as session, session.begin():
        await AccountService(session).create_customer(FIRST["phone_number"])

    await run_seeds(unseeded_session_factory, [InitCustomer(SETTINGS)])

    profiles = await profiles_by_phone(unseeded_session_factory)
    assert sorted(profiles) == sorted(sample["phone_number"] for sample in CUSTOMERS)
    # The pre-existing account was left as it was: no profile fields were written to it.
    assert profiles[FIRST["phone_number"]].email is None


async def test_a_sample_email_held_by_another_profile_fails_the_item_and_is_recorded(
    unseeded_session_factory: Factory,
) -> None:
    await run_seeds(unseeded_session_factory, [InitRoles()])
    async with unseeded_session_factory() as session, session.begin():
        await AccountService(session).create_password_account(FIRST["email"], "h", "s")

    with pytest.raises(SeedError, match="init.customer"):
        await run_seeds(unseeded_session_factory, [InitCustomer(SETTINGS)])

    recorded = await history(unseeded_session_factory)
    assert recorded["init.customer"][0] is False
    assert "EmailAlreadyRegisteredError" in str(recorded["init.customer"][1])
    # Rolled back: no customer of this item exists.
    assert sorted(await profiles_by_phone(unseeded_session_factory)) == ["None"]
