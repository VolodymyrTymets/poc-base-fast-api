"""OtpService: issue a one-time sign-in code for a phone number and hand it to the SMS channel (7.1), and check one (7.2: `find_challenge`, `check`, `spend`). Ports the
Node `OtpAuthStrategyService` and its code generator. Tasks: 7.1, 7.2. ADR-0021, ADR-0027, ADR-0028.

`issue` writes and flushes but never commits (ADR-0021); `deliver` is a separate call because the route commits in between: a job
must never carry a code the database does not hold. The code is stored only as an Argon2 hash (ADR-0028) and is valid for two minutes.
`spend` also writes and flushes only: the route commits after the tokens are issued, so a failure anywhere leaves the code unspent. The verify is three calls because the route ends the read transaction between `find_challenge` and `check`: Argon2 must not run with a pooled connection held.
"""

import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utc_now
from app.core.errors import InvalidCredentialsError
from app.core.hashing import hash_secret, verify_secret
from app.models import AccountIdentity, AccountProfile
from app.services.account import AccountService
from app.services.notifier import NotifierService, NotifierType

OTP_TTL = timedelta(minutes=2)
_CODE_DIGITS = 6
# A valid Argon2id hash (same cost as `hash_secret`) of a value nobody sends: `verify` checks against it when there is no usable code, so an
# unknown phone, a missing or an expired code cost about the same time as a wrong code and the 401 does not tell which numbers exist.
_DUMMY_HASH = "$argon2id$v=19$m=19456,t=2,p=1$much5sGO41ZuZ1RPLIa4eQ$WrkG3m+uQY4I7f754HVd4gVkq6L22XTF3jNs+sxWt0E"


def generate_code() -> str:
    """A uniformly random 6-digit code, 100000 to 999999 (never a leading zero, as in the Node base)."""
    low = 10 ** (_CODE_DIGITS - 1)
    return str(low + secrets.randbelow(9 * low))


@dataclass(frozen=True)
class IssuedOtp:
    account_id: str
    # repr=False: a dataclass repr lands in logs and tracebacks, and the code must not (rules D8, P4).
    code: str = field(repr=False)


@dataclass(frozen=True)
class OtpChallenge:
    """What `find_challenge` read: plain values, no ORM object, so it stays valid after the session's transaction ends."""

    account_id: str | None
    # repr=False: the stored hash must not land in logs or tracebacks (rules D8, P4). `None` when no code can be verified.
    otp_hash: str | None = field(repr=False)


class OtpService:
    def __init__(
        self,
        session: AsyncSession,
        accounts: AccountService,
        notifier: NotifierService,
    ) -> None:
        self._session = session
        self._accounts = accounts
        self._notifier = notifier

    async def issue(self, phone_number: str) -> IssuedOtp:
        """A new code for the account with this phone number, created as a customer when there is none.

        The hash and the expiry replace any earlier code; a password identity on the account keeps its own columns. The
        caller commits, then calls `deliver`. `phone_number` is already normalised (`PhoneNumber`).
        """
        # Hash before the first query: this endpoint is unauthenticated, and an await on the hash thread pool with a
        # transaction already open would hold a pooled connection for every queued request (a flood would starve
        # the authenticated routes of connections).
        code = generate_code()
        otp_hash = await hash_secret(code)
        expires_at = utc_now() + OTP_TTL

        account = await self._accounts.get_by_phone(phone_number)
        if account is None:
            account = await self._accounts.create_customer(phone_number)

        # One statement, not select-then-insert: the identity may not exist yet and two requests may race on it.
        # `otpSalt` is cleared, not written: the Argon2 string carries its own salt (ADR-0028).
        statement = insert(AccountIdentity).values(
            account_id=account.id,
            otp_hash=otp_hash,
            otp_salt=None,
            otp_expires_at=expires_at,
        )
        # `excluded` is keyed by the database column name ("otpHash"), not by the Python attribute.
        columns = AccountIdentity.__table__.c
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[columns.accountId],
                set_={
                    column: statement.excluded[column.name]
                    for column in (
                        columns.otpHash,
                        columns.otpSalt,
                        columns.otpExpiresAt,
                    )
                },
            )
        )
        await self._session.flush()
        return IssuedOtp(account.id, code)

    async def deliver(self, issued: IssuedOtp) -> None:
        """Queue the SMS job for an issued code. A queue that is down is logged by the notifier, not raised (ADR-0027)."""
        await self._notifier.notify_about_totp_code(
            issued.account_id, issued.code, [NotifierType.SMS]
        )

    async def find_challenge(self, phone_number: str) -> OtpChallenge:
        """Read what a verify of this phone needs: the account id and the stored code hash, `None`s when nothing can be verified.

        Reads only. The caller ends the read (the route rolls back) before `check`, so no pooled connection is held while Argon2 runs. An
        unknown or soft-deleted account or identity, no stored code and an expired one (`expires_at <= now`) all give a challenge with no hash.
        """
        account = await self._accounts.get_by_phone(phone_number)
        if account is None:
            return OtpChallenge(None, None)
        identity = await self._session.scalar(
            select(AccountIdentity).where(
                AccountIdentity.account_id == account.id,
                AccountIdentity.deleted.is_(False),
            )
        )
        if (
            identity is None
            or identity.otp_hash is None
            or identity.otp_expires_at is None
            or identity.otp_expires_at <= utc_now()
        ):
            return OtpChallenge(account.id, None)
        return OtpChallenge(account.id, identity.otp_hash)

    @staticmethod
    async def check(challenge: OtpChallenge, code: str) -> None:
        """Raise `InvalidCredentialsError` unless `code` matches the challenge's hash. Touches no database.

        Every failure is the same error (ENDPOINTS.md mapping decision 4; never `UnauthorizedError`, which makes a client refresh), and every
        path runs one Argon2 check, against a dummy hash when there is nothing to match, so the 401 timing does not reveal which phones exist.
        """
        matches = await verify_secret(code, challenge.otp_hash or _DUMMY_HASH)
        if challenge.account_id is None or challenge.otp_hash is None or not matches:
            raise InvalidCredentialsError

    async def spend(self, challenge: OtpChallenge) -> str:
        """Consume a checked code and mark the phone verified; returns the account id. Flushes, the caller commits.

        Single-use under concurrency: one conditional UPDATE on the hash `check` saw, so a request that finds the code already spent fails.
        """
        if challenge.account_id is None or challenge.otp_hash is None:
            raise InvalidCredentialsError
        spent = await self._session.scalar(
            update(AccountIdentity)
            .where(
                AccountIdentity.account_id == challenge.account_id,
                AccountIdentity.otp_hash == challenge.otp_hash,
                AccountIdentity.deleted.is_(False),
            )
            .values(otp_hash=None, otp_salt=None, otp_expires_at=None)
            .returning(AccountIdentity.id)
        )
        if spent is None:
            # A concurrent request spent this code between the read and the update.
            raise InvalidCredentialsError

        # Proving the code proves control of the phone; issuing tokens (TokenService) proves nothing about it.
        verified = await self._session.scalar(
            update(AccountProfile)
            .where(
                AccountProfile.account_id == challenge.account_id,
                AccountProfile.deleted.is_(False),
            )
            .values(is_phone_verified=True)
            .returning(AccountProfile.id)
        )
        if verified is None:
            raise InvalidCredentialsError
        await self._session.flush()
        return challenge.account_id

    @staticmethod
    async def verify_code(code: str, otp_hash: str) -> bool:
        """Whether `code` matches a stored `otpHash`; the expiry is `find_challenge`'s check."""
        return await verify_secret(code, otp_hash)
