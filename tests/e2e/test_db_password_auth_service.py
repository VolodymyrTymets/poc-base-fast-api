"""PasswordAuthService on a real Postgres. Tasks: 7.3 (sign-up and sign-in), 7.5 (change), 7.6 (restore and reset), ADR-0028."""

import asyncio
import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from time_machine import TimeMachineFixture
from utils.clock import FROZEN_NOW
from utils.locks import wait_for_a_lock_waiter
from utils.queue import FakeQueue

from app.config import Settings
from app.core.db import create_session_factory, utc_now
from app.core.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidResetTokenError,
)
from app.core.hashing import DUMMY_HASH, hash_secret, hash_token, verify_secret
from app.core.logging import JsonFormatter
from app.models import (
    Account,
    AccountIdentity,
    AccountOnRole,
    AccountProfile,
    AccountRole,
    AccountRoleType,
)
from app.services.account import AccountService
from app.services.account_profile import AccountProfileService
from app.services.file_assert import FileAssertService
from app.services.notifier import NotifierService
from app.services.password_auth import RESET_TOKEN_TTL, PasswordAuthService

PHRASE = "correct-horse-battery"


def unique_email() -> str:
    # Commits persist for the module (the concurrent test), so every test uses an address of its own.
    return f"{uuid.uuid4().hex}@example.com"


def service(
    session: AsyncSession, queue: FakeQueue | None = None
) -> PasswordAuthService:
    profiles = AccountProfileService(
        session, FileAssertService(session, Settings(database_url=None))
    )
    notifier = NotifierService(profiles, queue or FakeQueue())
    return PasswordAuthService(session, AccountService(session), notifier)


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


NEW_PHRASE = "another-correct-horse"
# Values of the shape the identity columns hold; only their being cleared matters.
STORED_REFRESH_HASH = "stored-refresh-hash"
STORED_RESET_HASH = "stored-reset-hash"


async def change_password(
    password_auth: PasswordAuthService,
    account_id: str,
    current: str,
    new: str,
) -> None:
    """The two steps the route runs, without its rollback between them (the savepoint session of `db_session` must keep the rows)."""
    credential = await password_auth.find_credential_for_account(account_id)
    await password_auth.change(credential, current, new)


async def test_change_stores_a_new_hash_that_verifies_the_new_password_only(
    db_session: AsyncSession,
) -> None:
    account_id = await service(db_session).sign_up(unique_email(), PHRASE)

    await change_password(service(db_session), account_id, PHRASE, NEW_PHRASE)

    identity = await identity_of(db_session, account_id)
    assert identity.hash is not None
    assert identity.hash.startswith("$argon2id$")
    assert (
        await verify_secret(NEW_PHRASE, identity.hash),
        await verify_secret(PHRASE, identity.hash),
        identity.salt,
    ) == (True, False, None)


async def test_change_clears_the_refresh_hash_the_reset_token_and_the_sign_in_code(
    db_session: AsyncSession,
) -> None:
    account_id = await service(db_session).sign_up(unique_email(), PHRASE)
    await db_session.execute(
        update(AccountIdentity)
        .where(AccountIdentity.account_id == account_id)
        .values(
            refresh_token=STORED_REFRESH_HASH,
            reset_token_hash=STORED_RESET_HASH,
            reset_token_expires_at=utc_now(),
            otp_hash="stored-otp-hash",
            otp_salt="stored-otp-salt",
            otp_expires_at=utc_now(),
        )
    )

    await change_password(service(db_session), account_id, PHRASE, NEW_PHRASE)

    identity = await identity_of(db_session, account_id)
    assert (
        identity.refresh_token,
        identity.reset_token_hash,
        identity.reset_token_expires_at,
        identity.otp_hash,
        identity.otp_salt,
        identity.otp_expires_at,
    ) == (None, None, None, None, None, None)


async def test_change_with_a_wrong_current_password_changes_nothing(
    db_session: AsyncSession,
) -> None:
    account_id = await service(db_session).sign_up(unique_email(), PHRASE)
    before = (await identity_of(db_session, account_id)).hash

    with pytest.raises(InvalidCredentialsError):
        await change_password(
            service(db_session), account_id, "not-the-phrase", NEW_PHRASE
        )

    assert (await identity_of(db_session, account_id)).hash == before


async def test_change_for_an_otp_only_account_is_invalid_credentials(
    db_session: AsyncSession,
) -> None:
    account = await AccountService(db_session).create_customer("+380000007302")
    db_session.add(AccountIdentity(account_id=account.id, otp_hash="otp"))
    await db_session.flush()

    with pytest.raises(InvalidCredentialsError):
        await change_password(service(db_session), account.id, PHRASE, NEW_PHRASE)


@pytest.mark.parametrize("record", ["account", "identity"])
async def test_change_for_a_soft_deleted_account_or_identity_is_invalid_credentials(
    db_session: AsyncSession, record: str
) -> None:
    account_id = await service(db_session).sign_up(unique_email(), PHRASE)
    await db_session.execute(SOFT_DELETES[record](account_id))

    with pytest.raises(InvalidCredentialsError):
        await change_password(service(db_session), account_id, PHRASE, NEW_PHRASE)


async def test_two_racing_changes_from_one_stored_hash_apply_exactly_one(
    db_engine: AsyncEngine,
) -> None:
    factory = create_session_factory(db_engine)
    email = unique_email()
    async with factory() as setup:
        account_id = await service(setup).sign_up(email, PHRASE)
        await setup.commit()

    async with factory() as first, factory() as second:
        # Both read the same stored hash. The first change holds its transaction open, so it holds the row lock; the second checks the
        # right current password, then waits on its UPDATE. Only when the test has seen it wait does the first commit, so the second
        # really races a committed change, and its conditional write must find the hash gone.
        first_credential = await service(first).find_credential_for_account(account_id)
        second_credential = await service(second).find_credential_for_account(
            account_id
        )
        await service(first).change(first_credential, PHRASE, NEW_PHRASE)
        loser = asyncio.create_task(
            service(second).change(second_credential, PHRASE, "the-losing-phrase")
        )
        await wait_for_a_lock_waiter(db_engine)
        await first.commit()
        with pytest.raises(InvalidCredentialsError):
            await asyncio.wait_for(loser, timeout=10)
        await second.rollback()

    async with factory() as check:
        stored = await check.scalar(
            select(AccountIdentity.hash).where(AccountIdentity.account_id == account_id)
        )
    assert stored is not None
    assert (
        await verify_secret(NEW_PHRASE, stored),
        await verify_secret("the-losing-phrase", stored),
    ) == (True, False)


def log_output(caplog: pytest.LogCaptureFixture) -> str:
    """The final JSON lines the API process would print for the captured records, including the traceback text."""
    formatter = JsonFormatter()
    return "\n".join(formatter.format(record) for record in caplog.records)


async def registered_email(session: AsyncSession) -> str:
    email = unique_email()
    await service(session).sign_up(email, PHRASE)
    return email


async def test_issue_stores_the_sha256_of_a_64_hex_token_and_never_the_token(
    db_session: AsyncSession, frozen_clock: TimeMachineFixture
) -> None:
    email = await registered_email(db_session)

    issued = await service(db_session).issue_reset_token(email)

    assert issued is not None
    identity = await identity_of(db_session, issued.account_id)
    assert (
        len(issued.token),
        identity.reset_token_hash == hash_token(issued.token),
        identity.reset_token_hash == issued.token,
        identity.reset_token_expires_at,
    ) == (
        64,
        True,
        False,
        FROZEN_NOW.replace(tzinfo=None) + RESET_TOKEN_TTL,
    )


async def test_a_second_issue_replaces_the_first_token(
    db_session: AsyncSession,
) -> None:
    email = await registered_email(db_session)
    first = await service(db_session).issue_reset_token(email)
    assert first is not None

    second = await service(db_session).issue_reset_token(email)

    assert second is not None
    identity = await identity_of(db_session, second.account_id)
    assert (second.token != first.token, identity.reset_token_hash) == (
        True,
        hash_token(second.token),
    )


async def test_issue_for_an_unknown_email_is_none_and_writes_nothing(
    db_session: AsyncSession,
) -> None:
    before = await db_session.scalar(select(func.count()).select_from(AccountIdentity))

    issued = await service(db_session).issue_reset_token(unique_email())

    after = await db_session.scalar(select(func.count()).select_from(AccountIdentity))
    assert (issued, after) == (None, before)


@pytest.mark.parametrize("record", list(SOFT_DELETES))
async def test_issue_for_a_soft_deleted_record_is_none_and_stores_no_token(
    db_session: AsyncSession, record: str
) -> None:
    email = unique_email()
    account_id = await service(db_session).sign_up(email, PHRASE)
    await db_session.execute(SOFT_DELETES[record](account_id))

    issued = await service(db_session).issue_reset_token(email)

    assert issued is None
    assert (await identity_of(db_session, account_id)).reset_token_hash is None


async def test_issue_creates_the_identity_of_an_account_that_has_none(
    db_session: AsyncSession,
) -> None:
    email = unique_email()
    account = await AccountService(db_session).create_customer("+380000007601")
    assert account.profile is not None
    account.profile.email = email
    await db_session.flush()

    issued = await service(db_session).issue_reset_token(email)

    assert issued is not None
    identity = await identity_of(db_session, account.id)
    assert (identity.hash, identity.reset_token_hash) == (
        None,
        hash_token(issued.token),
    )


async def test_issue_keeps_the_password_and_the_sign_in_code_of_the_identity(
    db_session: AsyncSession,
) -> None:
    email = unique_email()
    account_id = await service(db_session).sign_up(email, PHRASE)
    await db_session.execute(
        update(AccountIdentity)
        .where(AccountIdentity.account_id == account_id)
        .values(otp_hash="stored-otp-hash")
    )
    before = (await identity_of(db_session, account_id)).hash

    await service(db_session).issue_reset_token(email)

    identity = await identity_of(db_session, account_id)
    assert (identity.hash, identity.otp_hash) == (before, "stored-otp-hash")


async def test_deliver_queues_one_email_job_with_the_token(
    db_session: AsyncSession,
) -> None:
    queue = FakeQueue()
    email = await registered_email(db_session)
    issued = await service(db_session, queue).issue_reset_token(email)
    assert issued is not None

    await service(db_session, queue).deliver_reset_token(issued)

    jobs = queue.named("send_password_reset")
    assert len(jobs) == 1
    assert jobs[0].args == (issued.account_id, email, issued.token)


async def test_deliver_of_nothing_queues_nothing(db_session: AsyncSession) -> None:
    queue = FakeQueue()

    await service(db_session, queue).deliver_reset_token(None)

    assert queue.jobs == []


async def test_deliver_with_the_queue_down_logs_it_and_does_not_raise(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    queue = FakeQueue(fail_on=["send_password_reset"])
    email = await registered_email(db_session)
    issued = await service(db_session, queue).issue_reset_token(email)
    assert issued is not None

    await service(db_session, queue).deliver_reset_token(issued)

    expected = f"could not queue send_password_reset for account {issued.account_id}"
    assert expected in log_output(caplog)


async def test_issuing_and_delivering_log_no_token_or_email(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    queue = FakeQueue(fail_on=["send_password_reset"])
    email = await registered_email(db_session)
    caplog.set_level(logging.DEBUG)

    issued = await service(db_session, queue).issue_reset_token(email)
    await service(db_session, queue).deliver_reset_token(issued)

    assert issued is not None
    output = log_output(caplog)
    assert (issued.token in output, email in output) == (False, False)


async def reset_password(
    password_auth: PasswordAuthService, token: str, new: str
) -> None:
    """The two steps the route runs, without its rollback between them (the savepoint session of `db_session` must keep the rows)."""
    challenge = await password_auth.find_reset_challenge(token)
    await password_auth.reset(challenge, new)


async def issued_token(session: AsyncSession) -> tuple[str, str, str]:
    """A registered account's email, its id and a fresh reset token."""
    email = await registered_email(session)
    issued = await service(session).issue_reset_token(email)
    assert issued is not None
    return email, issued.account_id, issued.token


async def test_reset_sets_the_new_password_and_clears_the_credentials_of_the_old_one(
    db_session: AsyncSession,
) -> None:
    email, account_id, token = await issued_token(db_session)
    await db_session.execute(
        update(AccountIdentity)
        .where(AccountIdentity.account_id == account_id)
        .values(
            refresh_token=STORED_REFRESH_HASH,
            otp_hash="stored-otp-hash",
            otp_salt="stored-otp-salt",
            otp_expires_at=utc_now(),
        )
    )

    await reset_password(service(db_session), token, NEW_PHRASE)

    identity = await identity_of(db_session, account_id)
    credential = await service(db_session).find_credential(email)
    assert (
        await service(db_session).check(credential, NEW_PHRASE),
        identity.salt,
        identity.refresh_token,
        identity.reset_token_hash,
        identity.reset_token_expires_at,
        identity.otp_hash,
        identity.otp_salt,
        identity.otp_expires_at,
    ) == (account_id, None, None, None, None, None, None, None)


async def test_reset_stops_the_old_password(db_session: AsyncSession) -> None:
    email, _, token = await issued_token(db_session)
    await reset_password(service(db_session), token, NEW_PHRASE)

    with pytest.raises(InvalidCredentialsError):
        await sign_in(service(db_session), email, PHRASE)


async def test_a_reset_token_works_once(db_session: AsyncSession) -> None:
    _, _, token = await issued_token(db_session)
    await reset_password(service(db_session), token, NEW_PHRASE)

    with pytest.raises(InvalidResetTokenError):
        await reset_password(service(db_session), token, "a-third-phrase-1")


async def test_a_challenge_read_before_a_reset_cannot_reset_again_after_it(
    db_session: AsyncSession,
) -> None:
    _, _, token = await issued_token(db_session)
    stale = await service(db_session).find_reset_challenge(token)
    await reset_password(service(db_session), token, NEW_PHRASE)

    with pytest.raises(InvalidResetTokenError):
        await service(db_session).reset(stale, "a-third-phrase-1")


async def test_a_challenge_read_for_a_replaced_token_cannot_reset(
    db_session: AsyncSession,
) -> None:
    # The row's expiry is fresh again after the second restore, so only the token-hash condition of the UPDATE rejects the stale challenge.
    email = await registered_email(db_session)
    first = await service(db_session).issue_reset_token(email)
    assert first is not None
    stale = await service(db_session).find_reset_challenge(first.token)
    second = await service(db_session).issue_reset_token(email)
    assert second is not None

    with pytest.raises(InvalidResetTokenError):
        await service(db_session).reset(stale, NEW_PHRASE)

    await reset_password(service(db_session), second.token, NEW_PHRASE)


async def test_an_unknown_token_is_invalid_and_changes_nothing(
    db_session: AsyncSession,
) -> None:
    email = await registered_email(db_session)

    with pytest.raises(InvalidResetTokenError):
        await reset_password(service(db_session), "0" * 64, NEW_PHRASE)

    credential = await service(db_session).find_credential(email)
    assert await service(db_session).check(credential, PHRASE)


async def test_a_token_is_invalid_after_30_minutes(
    db_session: AsyncSession, frozen_clock: TimeMachineFixture
) -> None:
    _, _, token = await issued_token(db_session)
    frozen_clock.shift(RESET_TOKEN_TTL + timedelta(seconds=1))

    with pytest.raises(InvalidResetTokenError):
        await reset_password(service(db_session), token, NEW_PHRASE)


async def test_a_token_that_expires_between_the_read_and_the_write_is_rejected(
    db_session: AsyncSession, frozen_clock: TimeMachineFixture
) -> None:
    _, _, token = await issued_token(db_session)
    challenge = await service(db_session).find_reset_challenge(token)
    frozen_clock.shift(RESET_TOKEN_TTL + timedelta(seconds=1))

    with pytest.raises(InvalidResetTokenError):
        await service(db_session).reset(challenge, NEW_PHRASE)


@pytest.mark.parametrize("record", ["account", "identity"])
async def test_a_token_of_a_soft_deleted_account_or_identity_is_invalid(
    db_session: AsyncSession, record: str
) -> None:
    _, account_id, token = await issued_token(db_session)
    await db_session.execute(SOFT_DELETES[record](account_id))

    with pytest.raises(InvalidResetTokenError):
        await reset_password(service(db_session), token, NEW_PHRASE)


async def test_an_account_with_no_password_sets_its_first_one_with_a_reset(
    db_session: AsyncSession,
) -> None:
    email = unique_email()
    account = await AccountService(db_session).create_customer("+380000007602")
    assert account.profile is not None
    account.profile.email = email
    await db_session.flush()
    issued = await service(db_session).issue_reset_token(email)
    assert issued is not None

    await reset_password(service(db_session), issued.token, NEW_PHRASE)

    assert await sign_in(service(db_session), email, NEW_PHRASE) == account.id


async def test_a_garbage_token_runs_no_argon2_work(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    hashed: list[str] = []

    async def counting_hash_secret(secret: str) -> str:
        hashed.append(secret)
        return await hash_secret(secret)

    monkeypatch.setattr("app.services.password_auth.hash_secret", counting_hash_secret)

    with pytest.raises(InvalidResetTokenError):
        await reset_password(service(db_session), "garbage", NEW_PHRASE)

    assert hashed == []


async def test_two_racing_resets_with_one_token_apply_exactly_one(
    db_engine: AsyncEngine,
) -> None:
    factory = create_session_factory(db_engine)
    async with factory() as setup:
        email = await registered_email(setup)
        issued = await service(setup).issue_reset_token(email)
        assert issued is not None
        await setup.commit()

    async with factory() as first, factory() as second:
        # Both read the same live token. The first reset holds its transaction open, so it holds the row lock; the second waits on its UPDATE.
        # Only when the test has seen it wait does the first commit, so the second really races a committed reset, and its conditional
        # write must find the token gone.
        first_challenge = await service(first).find_reset_challenge(issued.token)
        second_challenge = await service(second).find_reset_challenge(issued.token)
        await service(first).reset(first_challenge, NEW_PHRASE)
        loser = asyncio.create_task(
            service(second).reset(second_challenge, "the-losing-phrase")
        )
        await wait_for_a_lock_waiter(db_engine)
        await first.commit()
        with pytest.raises(InvalidResetTokenError):
            await asyncio.wait_for(loser, timeout=10)
        await second.rollback()

    async with factory() as check:
        stored = await check.scalar(
            select(AccountIdentity.hash).where(
                AccountIdentity.account_id == issued.account_id
            )
        )
    assert stored is not None
    assert (
        await verify_secret(NEW_PHRASE, stored),
        await verify_secret("the-losing-phrase", stored),
    ) == (True, False)
