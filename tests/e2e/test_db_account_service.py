"""AccountService on a real Postgres (the template database holds the seeded roles). Task: 5.3."""

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utc_now
from app.models import (
    Account,
    AccountIdentity,
    AccountOnRole,
    AccountProfile,
    AccountRoleType,
)
from app.services.account import AccountService
from app.services.account_role import AccountRoleService


async def test_a_customer_has_the_phone_and_the_customer_role(
    db_session: AsyncSession,
) -> None:
    service = AccountService(db_session)

    account = await service.create_customer("+380501234567")

    assert account.profile is not None
    assert account.profile.phone_number == "+380501234567"
    assert account.profile.email is None
    assert account.identity is None
    assert await AccountRoleService(db_session).get_account_roles(account.id) == [
        AccountRoleType.CUSTOMER
    ]


async def test_a_password_account_has_profile_identity_and_role(
    db_session: AsyncSession,
) -> None:
    service = AccountService(db_session)

    account = await service.create_password_account("a@example.com", "h", "s")

    assert account.profile is not None
    assert account.profile.email == "a@example.com"
    assert account.profile.phone_number is None
    assert account.identity is not None
    assert (account.identity.hash, account.identity.salt) == ("h", "s")
    assert await AccountRoleService(db_session).get_account_roles(account.id) == [
        AccountRoleType.CUSTOMER
    ]


async def test_get_by_id_returns_the_account_with_its_profile(
    db_session: AsyncSession,
) -> None:
    service = AccountService(db_session)
    created = await service.create_password_account("b@example.com", "h", "s")
    account_id = created.id
    db_session.expire_all()

    found = await service.get_by_id(account_id)

    assert found is not None
    assert found.profile is not None
    assert found.profile.email == "b@example.com"


async def test_get_by_phone_finds_the_customer(db_session: AsyncSession) -> None:
    service = AccountService(db_session)
    created = await service.create_customer("+380509990001")

    found = await service.get_by_phone("+380509990001")

    assert found is not None
    assert found.id == created.id


async def test_unknown_id_and_phone_give_none(db_session: AsyncSession) -> None:
    service = AccountService(db_session)

    assert await service.get_by_id("00000000-0000-4000-8000-000000000000") is None
    assert await service.get_by_phone("+380509990002") is None


async def test_a_soft_deleted_account_is_not_found(db_session: AsyncSession) -> None:
    service = AccountService(db_session)
    account = await service.create_customer("+380509990003")
    await db_session.execute(
        update(Account).where(Account.id == account.id).values(deleted=True)
    )

    assert await service.get_by_id(account.id) is None
    assert await service.get_by_phone("+380509990003") is None


async def test_a_soft_deleted_profile_is_none_even_in_the_same_session(
    db_session: AsyncSession,
) -> None:
    service = AccountService(db_session)
    account = await service.create_password_account("c@example.com", "h", "s")
    assert account.profile is not None
    account.profile.deleted = True
    await db_session.flush()

    found = await service.get_by_id(account.id)

    assert found is not None
    assert found.profile is None


async def test_an_account_without_a_profile_has_none(db_session: AsyncSession) -> None:
    bare = Account(last_login_at=utc_now())
    db_session.add(bare)
    await db_session.flush()
    account_id = bare.id
    db_session.expire_all()

    found = await AccountService(db_session).get_by_id(account_id)

    assert found is not None
    assert found.profile is None


async def test_a_duplicate_email_fails_and_leaves_nothing(
    db_session: AsyncSession,
) -> None:
    service = AccountService(db_session)
    await service.create_password_account("d@example.com", "h", "s")
    accounts = await _count(db_session, Account)
    identities = await _count(db_session, AccountIdentity)
    links = await _count(db_session, AccountOnRole)

    savepoint = await db_session.begin_nested()
    with pytest.raises(IntegrityError):
        await service.create_password_account("d@example.com", "h2", "s2")
    await savepoint.rollback()

    assert await _count(db_session, Account) == accounts
    assert await _count(db_session, AccountProfile) == accounts
    assert await _count(db_session, AccountIdentity) == identities
    assert await _count(db_session, AccountOnRole) == links


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0
