"""PasswordAuthService on a real Postgres. Tasks: 7.3 (sign-up), ADR-0028."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import create_session_factory
from app.core.errors import EmailAlreadyRegisteredError
from app.core.hashing import verify_secret
from app.models import (
    Account,
    AccountIdentity,
    AccountOnRole,
    AccountProfile,
    AccountRole,
    AccountRoleType,
)
from app.services.account import AccountService
from app.services.password_auth import PasswordAuthService

PHRASE = "correct-horse-battery"


def unique_email() -> str:
    # Commits persist for the module (the concurrent test), so every test uses an address of its own.
    return f"{uuid.uuid4().hex}@example.com"


def service(session: AsyncSession) -> PasswordAuthService:
    return PasswordAuthService(session, AccountService(session))


async def identity_of(session: AsyncSession, account_id: str) -> AccountIdentity:
    result = await session.scalars(
        select(AccountIdentity).where(AccountIdentity.account_id == account_id)
    )
    return result.one()


async def count_profiles(session: AsyncSession, email: str) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(AccountProfile)
        .where(AccountProfile.email == email)
    )
    assert count is not None
    return count


async def test_sign_up_creates_a_customer_with_an_email_and_an_argon2_password(
    db_session: AsyncSession,
) -> None:
    email = unique_email()

    account_id = await service(db_session).sign_up(email, PHRASE)

    account = await AccountService(db_session).get_by_id(account_id)
    assert account is not None
    assert account.profile is not None
    assert account.profile.email == email
    identity = await identity_of(db_session, account_id)
    assert identity.hash is not None
    assert identity.hash.startswith("$argon2id$")
    assert await verify_secret(PHRASE, identity.hash)
    assert identity.salt is None
    assert identity.refresh_token is None


async def test_sign_up_puts_the_account_in_the_customer_role(
    db_session: AsyncSession,
) -> None:
    account_id = await service(db_session).sign_up(unique_email(), PHRASE)

    roles = await db_session.scalars(
        select(AccountRole.type)
        .join(AccountOnRole, AccountOnRole.role_id == AccountRole.id)
        .where(AccountOnRole.account_id == account_id)
    )
    assert list(roles) == [AccountRoleType.CUSTOMER]


async def test_sign_up_with_a_taken_email_fails_and_adds_nothing(
    db_session: AsyncSession,
) -> None:
    email = unique_email()
    await service(db_session).sign_up(email, PHRASE)
    accounts = await db_session.scalar(select(func.count()).select_from(Account))

    with pytest.raises(EmailAlreadyRegisteredError):
        await service(db_session).sign_up(email, "another-password")

    assert await count_profiles(db_session, email) == 1
    assert (
        await db_session.scalar(select(func.count()).select_from(Account)) == accounts
    )


async def test_sign_up_keeps_the_email_of_a_soft_deleted_profile_reserved(
    db_session: AsyncSession,
) -> None:
    email = unique_email()
    await service(db_session).sign_up(email, PHRASE)
    await db_session.execute(
        update(AccountProfile).where(AccountProfile.email == email).values(deleted=True)
    )

    with pytest.raises(EmailAlreadyRegisteredError):
        await service(db_session).sign_up(email, PHRASE)


async def test_two_concurrent_sign_ups_for_one_email_give_one_account_and_one_conflict(
    db_engine: AsyncEngine,
) -> None:
    email = unique_email()
    factory = create_session_factory(db_engine)

    async def attempt() -> str:
        async with factory() as session:
            try:
                account_id = await service(session).sign_up(email, PHRASE)
            except EmailAlreadyRegisteredError:
                await session.rollback()
                return "conflict"
            # The loser's insert waits on the unique index until this commit, so both must end their transaction.
            await session.commit()
            return account_id

    results = await asyncio.wait_for(asyncio.gather(attempt(), attempt()), timeout=30)

    assert sorted(r == "conflict" for r in results) == [False, True]
    async with factory() as session:
        assert await count_profiles(session, email) == 1
