"""TokenService on a real Postgres. Task: 7.2, ADR-0008. Ports the `jwt-strategy.service.spec.ts` cases of the Node base."""

import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.security import TokenType, verify_token
from app.models import AccountIdentity, AccountProfile
from app.services.account import AccountService
from app.services.tokens import TokenService

PHONE = "+380000000071"
# Values of the shape a password identity holds; only their survival matters.
STORED_HASH = "stored-password-hash"
STORED_SALT = "stored-password-salt"


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
