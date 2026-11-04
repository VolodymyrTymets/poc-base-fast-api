"""OtpService on a real Postgres with a recording queue. Task: 7.1, ADR-0028."""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from time_machine import TimeMachineFixture
from utils.clock import FROZEN_NOW
from utils.queue import EnqueuedJob, FakeQueue

from app.config import Settings
from app.core.logging import JsonFormatter
from app.models import AccountIdentity, AccountProfile, AccountRoleType
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
    """The final JSON lines the worker would print, including the traceback text."""
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
