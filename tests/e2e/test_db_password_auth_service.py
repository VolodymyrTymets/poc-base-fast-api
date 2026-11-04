"""PasswordAuthService on a real Postgres. Tasks: 7.3 (sign-up and sign-in), ADR-0028."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import create_session_factory
from app.core.errors import EmailAlreadyRegisteredError, InvalidCredentialsError
from app.core.hashing import DUMMY_HASH, verify_secret
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
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = unique_email()
    factory = create_session_factory(db_engine)
    # Both sign-ups must pass the pre-check before either inserts, or the loser is stopped by the pre-check and the
    # unique-index mapping is never reached (hashing time alone does not make the race happen).
    both_checked = asyncio.Barrier(2)
    real_create = AccountService.create_password_account

    async def create_after_both_checked(self: AccountService, *args: str) -> Account:
        await both_checked.wait()
        return await real_create(self, *args)

    monkeypatch.setattr(
        AccountService, "create_password_account", create_after_both_checked
    )

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


async def sign_in(password_auth: PasswordAuthService, email: str, phrase: str) -> str:
    """The two steps the route runs, without its rollback between them (the savepoint session of `db_session` must keep the rows)."""
    credential = await password_auth.find_credential(email)
    return await password_auth.check(credential, phrase)


async def test_sign_in_returns_the_account_id_for_the_right_password(
    db_session: AsyncSession,
) -> None:
    email = unique_email()
    account_id = await service(db_session).sign_up(email, PHRASE)

    assert await sign_in(service(db_session), email, PHRASE) == account_id


async def test_sign_in_wrong_password_is_invalid_credentials(
    db_session: AsyncSession,
) -> None:
    email = unique_email()
    await service(db_session).sign_up(email, PHRASE)

    with pytest.raises(InvalidCredentialsError):
        await sign_in(service(db_session), email, "not-the-phrase")


async def test_sign_in_unknown_email_is_invalid_credentials(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(InvalidCredentialsError):
        await sign_in(service(db_session), unique_email(), PHRASE)


async def test_sign_in_of_an_otp_only_account_is_invalid_credentials(
    db_session: AsyncSession,
) -> None:
    # An account with an email and an identity that holds no password hash (only an OTP, as the OTP path creates one).
    email = unique_email()
    account = await AccountService(db_session).create_customer("+380000007301")
    profile = account.profile
    assert profile is not None
    profile.email = email
    db_session.add(AccountIdentity(account_id=account.id, otp_hash="otp"))
    await db_session.flush()

    with pytest.raises(InvalidCredentialsError):
        await sign_in(service(db_session), email, PHRASE)


SOFT_DELETES = {
    "account": lambda account_id: (
        update(Account).where(Account.id == account_id).values(deleted=True)
    ),
    "profile": lambda account_id: (
        update(AccountProfile)
        .where(AccountProfile.account_id == account_id)
        .values(deleted=True)
    ),
    "identity": lambda account_id: (
        update(AccountIdentity)
        .where(AccountIdentity.account_id == account_id)
        .values(deleted=True)
    ),
}


@pytest.mark.parametrize("record", list(SOFT_DELETES))
async def test_sign_in_of_a_soft_deleted_record_is_invalid_credentials(
    db_session: AsyncSession, record: str
) -> None:
    email = unique_email()
    account_id = await service(db_session).sign_up(email, PHRASE)
    await db_session.execute(SOFT_DELETES[record](account_id))

    with pytest.raises(InvalidCredentialsError):
        await sign_in(service(db_session), email, PHRASE)


async def test_every_sign_in_failure_runs_one_argon2_check(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = unique_email()
    await service(db_session).sign_up(email, PHRASE)
    calls: list[str] = []
    real = verify_secret

    async def counting(secret: str, hashed: str) -> bool:
        calls.append(hashed)
        return await real(secret, hashed)

    # By name: the service imported the function, so the name in its own module is the one to replace.
    monkeypatch.setattr("app.services.password_auth.verify_secret", counting)

    with pytest.raises(InvalidCredentialsError):
        await sign_in(service(db_session), unique_email(), PHRASE)
    with pytest.raises(InvalidCredentialsError):
        await sign_in(service(db_session), email, "not-the-phrase")
    await sign_in(service(db_session), email, PHRASE)

    assert len(calls) == 3
    assert calls[0] == DUMMY_HASH
    assert calls[1] != DUMMY_HASH
