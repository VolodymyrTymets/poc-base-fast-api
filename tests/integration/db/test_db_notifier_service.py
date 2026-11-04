"""NotifierService on a real Postgres with a recording queue. Task: 6.3, ADR-0027."""

import logging
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from utils.queue import EnqueuedJob, FakeQueue

from app.config import Settings
from app.core.db import utc_now
from app.core.logging import JsonFormatter
from app.models import Account, AccountProfile
from app.services.account_profile import AccountProfileService
from app.services.file_assert import FileAssertService
from app.services.notifier import NotifierService, NotifierType

PHONE = "+380000000001"
EMAIL = "notify.me@example.test"
CODE = "482913"
RESET_VALUE = "fake-reset-value"
ALL = [NotifierType.ALL]


def notifier(session: AsyncSession, queue: FakeQueue) -> NotifierService:
    profiles = AccountProfileService(
        session, FileAssertService(session, Settings(database_url=None))
    )
    return NotifierService(profiles, queue)


async def make_account(
    session: AsyncSession, *, phone: str | None = PHONE, email: str | None = EMAIL
) -> str:
    account = Account(last_login_at=utc_now())
    session.add(account)
    await session.flush()
    session.add(AccountProfile(account_id=account.id, phone_number=phone, email=email))
    await session.flush()
    return account.id


def lines(caplog: pytest.LogCaptureFixture) -> str:
    """The final JSON lines the worker would print, including the traceback text."""
    formatter = JsonFormatter()
    return "\n".join(formatter.format(record) for record in caplog.records)


async def test_the_sms_channel_queues_the_code_for_the_profile_phone(
    db_session: AsyncSession,
) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session)

    await notifier(db_session, queue).notify_about_totp_code(
        account_id, CODE, [NotifierType.SMS]
    )

    assert queue.jobs == [EnqueuedJob("send_totp_code", (PHONE, CODE), {})]


async def test_the_email_channel_queues_the_reset_for_the_profile_email(
    db_session: AsyncSession,
) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session)

    await notifier(db_session, queue).notify_about_password_reset(
        account_id, RESET_VALUE, [NotifierType.EMAIL]
    )

    assert queue.jobs == [
        EnqueuedJob("send_password_reset", (account_id, EMAIL, RESET_VALUE), {})
    ]


async def test_all_sends_the_code_by_sms_only(db_session: AsyncSession) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session)

    await notifier(db_session, queue).notify_about_totp_code(account_id, CODE, ALL)

    assert [job.name for job in queue.jobs] == ["send_totp_code"]


async def test_all_sends_the_reset_by_email_only(db_session: AsyncSession) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session)

    await notifier(db_session, queue).notify_about_password_reset(
        account_id, RESET_VALUE, ALL
    )

    assert [job.name for job in queue.jobs] == ["send_password_reset"]


async def test_the_sms_channel_ignores_a_reset_and_the_email_channel_a_code(
    db_session: AsyncSession,
) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session)
    service = notifier(db_session, queue)

    await service.notify_about_password_reset(
        account_id, RESET_VALUE, [NotifierType.SMS]
    )
    await service.notify_about_totp_code(account_id, CODE, [NotifierType.EMAIL])

    assert queue.jobs == []


async def test_an_account_without_a_phone_gets_no_sms_job(
    db_session: AsyncSession,
) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session, phone=None)

    await notifier(db_session, queue).notify_about_totp_code(account_id, CODE, ALL)

    assert queue.jobs == []


async def test_an_account_without_an_email_gets_no_email_job(
    db_session: AsyncSession,
) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session, email=None)

    await notifier(db_session, queue).notify_about_password_reset(
        account_id, RESET_VALUE, ALL
    )

    assert queue.jobs == []


async def test_a_soft_deleted_profile_gets_nothing(db_session: AsyncSession) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session)
    await db_session.execute(
        update(AccountProfile)
        .where(AccountProfile.account_id == account_id)
        .values(deleted=True)
    )
    service = notifier(db_session, queue)

    await service.notify_about_totp_code(account_id, CODE, ALL)
    await service.notify_about_password_reset(account_id, RESET_VALUE, ALL)

    assert queue.jobs == []


async def test_an_unknown_account_gets_nothing_and_no_error(
    db_session: AsyncSession,
) -> None:
    queue = FakeQueue()
    service = notifier(db_session, queue)

    await service.notify_about_totp_code(str(uuid4()), CODE, ALL)
    await service.notify_about_password_reset(str(uuid4()), RESET_VALUE, ALL)

    assert queue.jobs == []


async def test_an_empty_list_of_types_queues_nothing(db_session: AsyncSession) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session)

    await notifier(db_session, queue).notify_about_totp_code(account_id, CODE, [])

    assert queue.jobs == []


async def test_a_channel_named_twice_is_used_once(db_session: AsyncSession) -> None:
    queue = FakeQueue()
    account_id = await make_account(db_session)

    await notifier(db_session, queue).notify_about_totp_code(
        account_id, CODE, [NotifierType.SMS, NotifierType.SMS, NotifierType.ALL]
    )

    assert [job.name for job in queue.jobs] == ["send_totp_code"]


async def test_a_queue_that_is_down_is_logged_and_the_other_channel_still_runs(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    account_id = await make_account(db_session)

    await notifier(
        db_session, FakeQueue(fail_on=["send_totp_code"])
    ).notify_about_totp_code(account_id, CODE, ALL)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert account_id in errors[0].getMessage()
    assert any(
        r.getMessage() == f"sign-in code issued for account {account_id}"
        for r in caplog.records
    )


async def test_a_reset_whose_queue_is_down_does_not_raise(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    account_id = await make_account(db_session)

    await notifier(
        db_session, FakeQueue(fail_on=["send_password_reset"])
    ).notify_about_password_reset(account_id, RESET_VALUE, ALL)

    assert [r.levelname for r in caplog.records] == ["INFO", "ERROR"]


class BrokenQueue:
    """A queue with a bug, not an outage: it raises something that is not `QueueUnavailableError`."""

    async def enqueue(self, job_name: str, *args: object, **kwargs: object) -> None:
        raise RuntimeError("a bug in the queue")


async def test_any_other_queue_error_propagates(db_session: AsyncSession) -> None:
    profiles = AccountProfileService(
        db_session, FileAssertService(db_session, Settings(database_url=None))
    )
    account_id = await make_account(db_session)

    with pytest.raises(RuntimeError, match="a bug in the queue"):
        await NotifierService(profiles, BrokenQueue()).notify_about_totp_code(
            account_id, CODE, ALL
        )


async def test_no_log_line_holds_the_code_the_token_the_email_or_the_phone(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    account_id = await make_account(db_session)
    service = notifier(
        db_session, FakeQueue(fail_on=["send_totp_code", "send_password_reset"])
    )

    await service.notify_about_totp_code(account_id, CODE, ALL)
    await service.notify_about_password_reset(account_id, RESET_VALUE, ALL)

    # The raw records too: the formatter redacts phone numbers, which must not be what makes this pass.
    raw = "\n".join(
        f"{record.getMessage()} {record.args!r} {record.exc_text or ''}"
        for record in caplog.records
    )
    assert caplog.records
    for secret in (CODE, RESET_VALUE, EMAIL, PHONE):
        assert secret not in lines(caplog)
        assert secret not in raw
