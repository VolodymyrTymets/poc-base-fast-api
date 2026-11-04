"""OtpService on a real Postgres with a recording queue. Tasks: 7.1 (issue), 7.2 (verify), ADR-0028."""

import asyncio
import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from time_machine import TimeMachineFixture
from utils.clock import FROZEN_NOW
from utils.queue import EnqueuedJob, FakeQueue

from app.config import Settings
from app.core.errors import InvalidCredentialsError
from app.core.logging import JsonFormatter
from app.models import Account, AccountIdentity, AccountProfile, AccountRoleType
from app.services.account import AccountService
from app.services.account_profile import AccountProfileService
from app.services.account_role import AccountRoleService
from app.services.file_assert import FileAssertService
from app.services.notifier import NotifierService
from app.services.otp import OTP_TTL, OtpService

PHONE = "+380000000001"
# Values of the shape a password identity holds; only their survival matters.
STORED_HASH = "stored-password-hash"
STORED_SALT = "stored-password-salt"


def otp_service(session: AsyncSession, queue: FakeQueue) -> OtpService:
    profiles = AccountProfileService(
        session, FileAssertService(session, Settings(database_url=None))
    )
    return OtpService(
        session, AccountService(session), NotifierService(profiles, queue)
    )


async def identity_of(session: AsyncSession, account_id: str) -> AccountIdentity:
    result = await session.scalars(
        select(AccountIdentity).where(AccountIdentity.account_id == account_id)
    )
    return result.one()


async def accounts_with_phone(session: AsyncSession, phone: str) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(AccountProfile)
        .where(AccountProfile.phone_number == phone)
    )
    assert count is not None
    return count


def lines(caplog: pytest.LogCaptureFixture) -> str:
    """The final JSON lines the API process would print for the captured records, including the traceback text."""
    formatter = JsonFormatter()
    return "\n".join(formatter.format(record) for record in caplog.records)


async def test_an_unknown_phone_gets_a_customer_account_and_an_identity_with_a_code(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)

    issued = await service.issue(PHONE)

    identity = await identity_of(db_session, issued.account_id)
    assert identity.otp_hash is not None
    assert (
        await accounts_with_phone(db_session, PHONE),
        await AccountRoleService(db_session).get_account_roles(issued.account_id),
        await service.verify_code(issued.code, identity.otp_hash),
    ) == (1, [AccountRoleType.CUSTOMER], True)


async def test_the_stored_code_is_a_hash_that_expires_two_minutes_later(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    issued = await otp_service(db_session, queue).issue(PHONE)

    identity = await identity_of(db_session, issued.account_id)
    assert identity.otp_hash is not None
    assert (
        identity.otp_hash.startswith("$argon2id$"),
        issued.code in identity.otp_hash,
        identity.otp_salt,
        identity.otp_expires_at,
    ) == (True, False, None, (FROZEN_NOW + OTP_TTL).replace(tzinfo=None))


async def test_a_second_request_for_the_same_phone_replaces_the_code_and_adds_no_account(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    first = await service.issue(PHONE)
    first_hash = (await identity_of(db_session, first.account_id)).otp_hash
    frozen_clock.shift(timedelta(seconds=30))

    second = await service.issue(PHONE)

    identity = await identity_of(db_session, second.account_id)
    await db_session.refresh(identity)
    assert identity.otp_hash is not None
    assert (
        second.account_id,
        await accounts_with_phone(db_session, PHONE),
        identity.otp_hash != first_hash,
        await service.verify_code(second.code, identity.otp_hash),
        identity.otp_expires_at,
    ) == (
        first.account_id,
        1,
        True,
        True,
        (FROZEN_NOW + timedelta(seconds=30) + OTP_TTL).replace(tzinfo=None),
    )


async def test_an_existing_customer_without_an_identity_gets_one_and_no_second_account(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    customer = await AccountService(db_session).create_customer(PHONE)

    issued = await otp_service(db_session, queue).issue(PHONE)

    identity = await identity_of(db_session, customer.id)
    assert (
        issued.account_id,
        await accounts_with_phone(db_session, PHONE),
        identity.otp_hash is not None,
    ) == (customer.id, 1, True)


async def test_a_code_request_leaves_the_password_columns_of_the_identity_alone(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    customer = await AccountService(db_session).create_customer(PHONE)
    db_session.add(
        AccountIdentity(account_id=customer.id, hash=STORED_HASH, salt=STORED_SALT)
    )
    await db_session.flush()

    await otp_service(db_session, queue).issue(PHONE)

    identity = await identity_of(db_session, customer.id)
    await db_session.refresh(identity)
    assert (identity.hash, identity.salt, identity.otp_hash is not None) == (
        STORED_HASH,
        STORED_SALT,
        True,
    )


async def test_issue_queues_nothing_until_deliver_is_called(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)

    issued = await service.issue(PHONE)
    before = queue.jobs
    await service.deliver(issued)

    assert (before, queue.jobs) == (
        [],
        [EnqueuedJob("send_totp_code", (PHONE, issued.code), {})],
    )


async def test_deliver_with_the_queue_down_returns_and_logs_without_the_code_or_phone(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    frozen_clock: TimeMachineFixture,
) -> None:
    queue = FakeQueue(fail_on=["send_totp_code"])
    service = otp_service(db_session, queue)
    issued = await service.issue(PHONE)

    with caplog.at_level(logging.INFO):
        await service.deliver(issued)

    output = lines(caplog)
    assert (
        queue.jobs,
        issued.account_id in output,
        issued.code in output,
        PHONE in output,
    ) == ([], True, False, False)


# --- verify (task 7.2) -------------------------------------------------------------------------------------------------------------------

VERIFY_PHONE = "+380000000072"


async def profile_of(session: AsyncSession, account_id: str) -> AccountProfile:
    result = await session.scalars(
        select(AccountProfile).where(AccountProfile.account_id == account_id)
    )
    profile = result.one()
    await session.refresh(profile)
    return profile


async def test_a_valid_code_returns_the_account_clears_the_code_and_verifies_the_phone(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)

    account_id = await service.verify(VERIFY_PHONE, issued.code)

    identity = await identity_of(db_session, account_id)
    await db_session.refresh(identity)
    assert (
        account_id,
        identity.otp_hash,
        identity.otp_salt,
        identity.otp_expires_at,
        (await profile_of(db_session, account_id)).is_phone_verified,
    ) == (issued.account_id, None, None, None, True)


async def test_a_wrong_code_fails_and_changes_nothing(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)

    with pytest.raises(InvalidCredentialsError):
        await service.verify(VERIFY_PHONE, "000000")

    identity = await identity_of(db_session, issued.account_id)
    assert (
        identity.otp_hash is not None,
        (await profile_of(db_session, issued.account_id)).is_phone_verified,
        await service.verify(VERIFY_PHONE, issued.code),
    ) == (True, False, issued.account_id)


async def test_an_unknown_phone_fails(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    with pytest.raises(InvalidCredentialsError):
        await otp_service(db_session, queue).verify("+380000000099", "123456")


async def test_an_account_without_an_identity_fails(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    await AccountService(db_session).create_customer(VERIFY_PHONE)

    with pytest.raises(InvalidCredentialsError):
        await otp_service(db_session, queue).verify(VERIFY_PHONE, "123456")


async def test_an_identity_without_a_code_fails(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    account = await AccountService(db_session).create_customer(VERIFY_PHONE)
    db_session.add(AccountIdentity(account_id=account.id, hash=STORED_HASH))
    await db_session.flush()

    with pytest.raises(InvalidCredentialsError):
        await otp_service(db_session, queue).verify(VERIFY_PHONE, "123456")


async def test_a_code_is_still_good_one_second_before_the_two_minutes_end(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)
    frozen_clock.shift(OTP_TTL - timedelta(seconds=1))

    assert await service.verify(VERIFY_PHONE, issued.code) == issued.account_id


async def test_a_code_is_expired_at_exactly_two_minutes(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)
    frozen_clock.shift(OTP_TTL)

    with pytest.raises(InvalidCredentialsError):
        await service.verify(VERIFY_PHONE, issued.code)

    identity = await identity_of(db_session, issued.account_id)
    assert identity.otp_hash is not None


async def test_a_code_works_once(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)
    await service.verify(VERIFY_PHONE, issued.code)

    with pytest.raises(InvalidCredentialsError):
        await service.verify(VERIFY_PHONE, issued.code)


async def test_a_new_request_kills_the_previous_code(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    first = await service.issue(VERIFY_PHONE)
    second = await service.issue(VERIFY_PHONE)

    with pytest.raises(InvalidCredentialsError):
        await service.verify(VERIFY_PHONE, first.code)
    assert await service.verify(VERIFY_PHONE, second.code) == second.account_id


async def test_verify_keeps_the_password_columns_of_the_identity(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    account = await AccountService(db_session).create_customer(VERIFY_PHONE)
    db_session.add(
        AccountIdentity(account_id=account.id, hash=STORED_HASH, salt=STORED_SALT)
    )
    await db_session.flush()
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)

    await service.verify(VERIFY_PHONE, issued.code)

    identity = await identity_of(db_session, account.id)
    await db_session.refresh(identity)
    assert (identity.hash, identity.salt) == (STORED_HASH, STORED_SALT)


async def test_a_soft_deleted_account_fails(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)
    await db_session.execute(
        update(Account).where(Account.id == issued.account_id).values(deleted=True)
    )

    with pytest.raises(InvalidCredentialsError):
        await service.verify(VERIFY_PHONE, issued.code)


async def test_a_soft_deleted_identity_fails_and_keeps_its_code(
    db_session: AsyncSession, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)
    await db_session.execute(
        update(AccountIdentity)
        .where(AccountIdentity.account_id == issued.account_id)
        .values(deleted=True)
    )

    with pytest.raises(InvalidCredentialsError):
        await service.verify(VERIFY_PHONE, issued.code)

    identity = await identity_of(db_session, issued.account_id)
    await db_session.refresh(identity)
    assert identity.otp_hash is not None


async def test_two_concurrent_verifies_of_one_code_let_exactly_one_through(
    db_engine: AsyncEngine, queue: FakeQueue, frozen_clock: TimeMachineFixture
) -> None:
    # Own sessions that commit: `verify` never commits, so a shared savepoint session could not show the row lock at work.
    phone = "+380000000073"
    async with AsyncSession(db_engine, expire_on_commit=False) as setup:
        issued = await otp_service(setup, queue).issue(phone)
        await setup.commit()

    async def attempt() -> str | None:
        async with AsyncSession(db_engine, expire_on_commit=False) as session:
            try:
                account_id = await otp_service(session, queue).verify(
                    phone, issued.code
                )
            except InvalidCredentialsError:
                await session.rollback()
                return None
            await session.commit()
            return account_id

    results = await asyncio.gather(attempt(), attempt())

    assert sorted(r is None for r in results) == [False, True]


async def test_a_failed_verify_logs_neither_the_code_nor_the_phone(
    db_session: AsyncSession,
    queue: FakeQueue,
    frozen_clock: TimeMachineFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = otp_service(db_session, queue)
    issued = await service.issue(VERIFY_PHONE)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(InvalidCredentialsError):
        await service.verify(VERIFY_PHONE, "000000")
    await service.verify(VERIFY_PHONE, issued.code)

    output = lines(caplog)
    assert (issued.code in output, VERIFY_PHONE in output) == (False, False)
