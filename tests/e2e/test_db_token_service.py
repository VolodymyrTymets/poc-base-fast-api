"""TokenService on a real Postgres. Tasks: 7.2 (issue), 7.4 (rotate, revoke), ADR-0008. Ports the `jwt-strategy.service.spec.ts` cases of the Node base."""

import asyncio
import hashlib
import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.db import create_session_factory, utc_now
from app.core.errors import UnauthorizedError
from app.core.security import TokenType, issue_token, verify_token
from app.models import Account, AccountIdentity, AccountProfile
from app.services.account import AccountService
from app.services.tokens import TokenService

PHONE = "+380000000071"
# Values of the shape a password identity holds; only their survival matters.
STORED_HASH = "stored-password-hash"
STORED_SALT = "stored-password-salt"
STORED_REFRESH_HASH = "stored-refresh-hash"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=None,
        jwt_secret=ACCESS_KEY,
        jwt_refresh_token_secret=REFRESH_KEY,
    )


async def new_account_id(session: AsyncSession, phone: str = PHONE) -> str:
    return (await AccountService(session).create_customer(phone)).id


async def identity_of(session: AsyncSession, account_id: str) -> AccountIdentity:
    result = await session.scalars(
        select(AccountIdentity).where(AccountIdentity.account_id == account_id)
    )
    identity = result.one()
    await session.refresh(identity)
    return identity


async def test_the_pair_verifies_with_each_secret_and_names_the_account(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)

    pair = await TokenService(db_session, settings).issue(account_id)

    access = verify_token(settings, pair.access_token, TokenType.ACCESS)
    refresh = verify_token(settings, pair.refresh_token, TokenType.REFRESH)
    assert (access.account_id, refresh.account_id) == (account_id, account_id)


async def test_the_stored_value_is_the_sha256_of_the_refresh_token_not_the_token(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)

    pair = await TokenService(db_session, settings).issue(account_id)

    identity = await identity_of(db_session, account_id)
    assert (
        identity.refresh_token,
        identity.refresh_token == pair.refresh_token,
    ) == (hashlib.sha256(pair.refresh_token.encode()).hexdigest(), False)


async def test_a_second_issue_gives_a_different_pair_and_replaces_the_stored_hash(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)
    service = TokenService(db_session, settings)

    first = await service.issue(account_id)
    second = await service.issue(account_id)

    identity = await identity_of(db_session, account_id)
    assert (
        first.refresh_token != second.refresh_token,
        first.access_token != second.access_token,
        identity.refresh_token,
    ) == (
        True,
        True,
        hashlib.sha256(second.refresh_token.encode()).hexdigest(),
    )


async def test_an_existing_identity_keeps_its_password_and_otp_columns(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)
    db_session.add(
        AccountIdentity(
            account_id=account_id,
            hash=STORED_HASH,
            salt=STORED_SALT,
            otp_hash="stored-otp-hash",
        )
    )
    await db_session.flush()

    await TokenService(db_session, settings).issue(account_id)

    identity = await identity_of(db_session, account_id)
    assert (identity.hash, identity.salt, identity.otp_hash) == (
        STORED_HASH,
        STORED_SALT,
        "stored-otp-hash",
    )


async def test_issuing_tokens_does_not_mark_the_phone_verified(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)

    await TokenService(db_session, settings).issue(account_id)

    verified = await db_session.scalar(
        select(AccountProfile.is_phone_verified).where(
            AccountProfile.account_id == account_id
        )
    )
    assert verified is False


def sha256_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def test_rotate_gives_a_new_pair_and_stores_the_hash_of_the_new_refresh_token(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)
    service = TokenService(db_session, settings)
    first = await service.issue(account_id)

    second = await service.rotate(account_id, first.refresh_token)

    identity = await identity_of(db_session, account_id)
    assert second.refresh_token != first.refresh_token
    assert identity.refresh_token == sha256_of(second.refresh_token)


async def test_the_old_refresh_token_is_rejected_after_a_rotation(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)
    service = TokenService(db_session, settings)
    first = await service.issue(account_id)
    await service.rotate(account_id, first.refresh_token)

    with pytest.raises(UnauthorizedError):
        await service.rotate(account_id, first.refresh_token)


async def test_rotate_rejects_an_account_with_no_stored_refresh_hash(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)
    service = TokenService(db_session, settings)
    pair = await service.issue(account_id)
    await service.revoke(account_id)

    with pytest.raises(UnauthorizedError):
        await service.rotate(account_id, pair.refresh_token)


async def test_rotate_rejects_an_account_that_has_no_identity_row(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)
    # A validly signed refresh token for an account that never stored one.
    token = issue_token(settings, account_id, TokenType.REFRESH)

    with pytest.raises(UnauthorizedError):
        await TokenService(db_session, settings).rotate(account_id, token)


async def test_rotate_rejects_the_refresh_token_of_another_account(
    db_session: AsyncSession, settings: Settings
) -> None:
    mine = await new_account_id(db_session, "+380000000072")
    theirs = await new_account_id(db_session, "+380000000073")
    service = TokenService(db_session, settings)
    await service.issue(mine)
    others = await service.issue(theirs)

    with pytest.raises(UnauthorizedError):
        await service.rotate(mine, others.refresh_token)


async def test_rotate_rejects_an_access_token_in_place_of_the_refresh_token(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)
    service = TokenService(db_session, settings)
    pair = await service.issue(account_id)

    with pytest.raises(UnauthorizedError):
        await service.rotate(account_id, pair.access_token)


SOFT_DELETES = {
    "account": lambda account_id: (
        update(Account).where(Account.id == account_id).values(deleted=True)
    ),
    "identity": lambda account_id: (
        update(AccountIdentity)
        .where(AccountIdentity.account_id == account_id)
        .values(deleted=True)
    ),
}


@pytest.mark.parametrize("record", list(SOFT_DELETES))
async def test_rotate_rejects_a_soft_deleted_account_or_identity(
    db_session: AsyncSession, settings: Settings, record: str
) -> None:
    account_id = await new_account_id(db_session)
    service = TokenService(db_session, settings)
    pair = await service.issue(account_id)
    await db_session.execute(SOFT_DELETES[record](account_id))

    with pytest.raises(UnauthorizedError):
        await service.rotate(account_id, pair.refresh_token)


async def test_revoke_clears_the_refresh_hash_and_the_sign_in_code_and_keeps_the_password(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)
    db_session.add(
        AccountIdentity(
            account_id=account_id,
            hash=STORED_HASH,
            salt=STORED_SALT,
            refresh_token=STORED_REFRESH_HASH,
            otp_hash="stored-otp-hash",
            otp_salt="stored-otp-salt",
            otp_expires_at=utc_now(),
        )
    )
    await db_session.flush()

    await TokenService(db_session, settings).revoke(account_id)

    identity = await identity_of(db_session, account_id)
    assert (
        identity.refresh_token,
        identity.otp_hash,
        identity.otp_salt,
        identity.otp_expires_at,
        identity.hash,
        identity.salt,
    ) == (None, None, None, None, STORED_HASH, STORED_SALT)


async def test_revoke_of_an_account_with_no_identity_row_does_nothing(
    db_session: AsyncSession, settings: Settings
) -> None:
    account_id = await new_account_id(db_session)

    await TokenService(db_session, settings).revoke(account_id)

    found = await db_session.scalar(
        select(AccountIdentity.id).where(AccountIdentity.account_id == account_id)
    )
    assert found is None


async def lock_waiters(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        count = await connection.scalar(
            text(
                "select count(*) from pg_stat_activity "
                "where wait_event_type = 'Lock' and datname = current_database()"
            )
        )
    assert count is not None
    return int(count)


async def wait_for_a_lock_waiter(engine: AsyncEngine) -> None:
    # Polls a condition with a bound (about 10 s), not a guess at how long the other transaction needs.
    for _ in range(500):
        if await lock_waiters(engine) > 0:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("no transaction waited on a row lock within 10 seconds")


async def test_two_rotations_with_one_token_give_one_winner_and_one_rejection(
    db_engine: AsyncEngine, settings: Settings
) -> None:
    factory = create_session_factory(db_engine)
    phone = f"+38000{uuid.uuid4().int % 10**7:07d}"
    async with factory() as setup:
        account_id = await new_account_id(setup, phone)
        issued = await TokenService(setup, settings).issue(account_id)
        await setup.commit()

    async with factory() as first, factory() as second:
        # The first rotation holds its transaction open, so it holds the row lock. The second reads the old hash, matches it and then waits
        # on its UPDATE; only when the test has seen it wait does the first commit, so the second really races a committed swap.
        winner = await TokenService(first, settings).rotate(
            account_id, issued.refresh_token
        )
        loser = asyncio.create_task(
            TokenService(second, settings).rotate(account_id, issued.refresh_token)
        )
        await wait_for_a_lock_waiter(db_engine)
        await first.commit()
        with pytest.raises(UnauthorizedError):
            await asyncio.wait_for(loser, timeout=10)
        await second.rollback()

    async with factory() as check:
        stored = await check.scalar(
            select(AccountIdentity.refresh_token).where(
                AccountIdentity.account_id == account_id
            )
        )
    assert stored == sha256_of(winner.refresh_token)
