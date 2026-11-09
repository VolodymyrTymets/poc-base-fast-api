"""AccountRoleService on a real Postgres (the template database holds the seeded roles). Task: 5.2."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from utils.cache import MemoryStore
from utils.sql import count_statements

from app.core.cache import ReadCache, cache_key
from app.models import Account, AccountOnRole, AccountRole, AccountRoleType
from app.services.account_role import (
    ROLE_CACHE_MODEL,
    AccountRoleService,
    RoleNotFoundError,
)


async def make_account(session: AsyncSession) -> str:
    account = Account(last_login_at=datetime.now(UTC).replace(tzinfo=None))
    session.add(account)
    await session.flush()
    return account.id


async def test_an_account_with_no_link_has_no_roles(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session)

    assert await AccountRoleService(db_session).get_account_roles(account_id) == []


async def test_a_role_added_is_returned(db_session: AsyncSession) -> None:
    service = AccountRoleService(db_session)
    account_id = await make_account(db_session)

    link = await service.add_account_to_role(account_id, AccountRoleType.CUSTOMER)

    assert link.account_id == account_id
    assert await service.get_account_roles(account_id) == [AccountRoleType.CUSTOMER]


async def test_both_roles_are_returned(db_session: AsyncSession) -> None:
    service = AccountRoleService(db_session)
    account_id = await make_account(db_session)
    await service.add_account_to_role(account_id, AccountRoleType.CUSTOMER)
    await service.add_account_to_role(account_id, AccountRoleType.ADMIN)

    roles = await service.get_account_roles(account_id)

    assert sorted(roles) == [AccountRoleType.ADMIN, AccountRoleType.CUSTOMER]


async def test_another_accounts_roles_are_not_returned(
    db_session: AsyncSession,
) -> None:
    service = AccountRoleService(db_session)
    first = await make_account(db_session)
    second = await make_account(db_session)
    await service.add_account_to_role(first, AccountRoleType.ADMIN)

    assert await service.get_account_roles(second) == []


async def test_a_soft_deleted_link_does_not_count(db_session: AsyncSession) -> None:
    service = AccountRoleService(db_session)
    account_id = await make_account(db_session)
    await service.add_account_to_role(account_id, AccountRoleType.ADMIN)
    await db_session.execute(
        update(AccountOnRole)
        .where(AccountOnRole.account_id == account_id)
        .values(deleted=True)
    )

    assert await service.get_account_roles(account_id) == []


async def test_a_soft_deleted_role_does_not_count(db_session: AsyncSession) -> None:
    service = AccountRoleService(db_session)
    account_id = await make_account(db_session)
    await service.add_account_to_role(account_id, AccountRoleType.ADMIN)
    await db_session.execute(
        update(AccountRole)
        .where(AccountRole.type == AccountRoleType.ADMIN)
        .values(deleted=True)
    )

    assert await service.get_account_roles(account_id) == []


async def test_adding_a_role_with_no_live_role_row_raises(
    db_session: AsyncSession,
) -> None:
    account_id = await make_account(db_session)
    await db_session.execute(
        update(AccountRole)
        .where(AccountRole.type == AccountRoleType.ADMIN)
        .values(deleted=True)
    )

    with pytest.raises(RoleNotFoundError, match="ADMIN"):
        await AccountRoleService(db_session).add_account_to_role(
            account_id, AccountRoleType.ADMIN
        )


async def test_adding_the_same_role_twice_is_not_swallowed(
    db_session: AsyncSession,
) -> None:
    service = AccountRoleService(db_session)
    account_id = await make_account(db_session)
    await service.add_account_to_role(account_id, AccountRoleType.CUSTOMER)
    # A fresh identity map, as a second request has: the same object twice would only trip an SQLAlchemy warning.
    db_session.expunge_all()

    with pytest.raises(IntegrityError):
        await service.add_account_to_role(account_id, AccountRoleType.CUSTOMER)


async def test_add_is_flushed_so_the_row_is_visible_in_the_same_transaction(
    db_session: AsyncSession,
) -> None:
    account_id = await make_account(db_session)
    await AccountRoleService(db_session).add_account_to_role(
        account_id, AccountRoleType.CUSTOMER
    )

    # The service never calls commit (ADR-0021); this proves the flush, a plain query sees the row.
    count = await db_session.scalars(
        select(AccountOnRole).where(AccountOnRole.account_id == account_id)
    )
    assert len(list(count)) == 1


async def test_roles_read_a_second_time_run_no_sql_and_are_role_types(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    # Arrange
    service = AccountRoleService(db_session, cache=ReadCache(MemoryStore()))
    account_id = await make_account(db_session)
    await service.add_account_to_role(account_id, AccountRoleType.ADMIN)
    await service.get_account_roles(account_id)

    # Act
    with count_statements(db_engine) as statements:
        roles = await service.get_account_roles(account_id)

    # Assert
    assert (statements, roles, type(roles[0])) == (
        [],
        [AccountRoleType.ADMIN],
        AccountRoleType,
    )


async def test_an_account_with_no_role_is_not_cached(db_session: AsyncSession) -> None:
    # Arrange
    store = MemoryStore()
    service = AccountRoleService(db_session, cache=ReadCache(store))
    account_id = await make_account(db_session)

    # Act
    roles = await service.get_account_roles(account_id)

    # Assert
    assert (roles, store.data) == ([], {})


async def test_a_role_added_after_an_empty_read_shows_at_once(
    db_session: AsyncSession,
) -> None:
    # Arrange
    service = AccountRoleService(db_session, cache=ReadCache(MemoryStore()))
    account_id = await make_account(db_session)
    await service.get_account_roles(account_id)
    await service.add_account_to_role(account_id, AccountRoleType.CUSTOMER)

    # Act
    roles = await service.get_account_roles(account_id)

    # Assert
    assert roles == [AccountRoleType.CUSTOMER]


async def test_a_cached_entry_with_an_unknown_role_is_reloaded(
    db_session: AsyncSession,
) -> None:
    # Arrange
    store = MemoryStore()
    service = AccountRoleService(db_session, cache=ReadCache(store))
    account_id = await make_account(db_session)
    await service.add_account_to_role(account_id, AccountRoleType.CUSTOMER)
    store.data[cache_key(ROLE_CACHE_MODEL, {"accountId": account_id})] = '["GHOST"]'

    # Act
    roles = await service.get_account_roles(account_id)

    # Assert
    assert roles == [AccountRoleType.CUSTOMER]
