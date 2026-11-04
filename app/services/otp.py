"""OtpService: issue a one-time sign-in code for a phone number and hand it to the SMS channel. Ports the request half of the Node
`OtpAuthStrategyService` and its code generator. Tasks: 7.1 (7.2 adds the verify half). ADR-0021, ADR-0027, ADR-0028.

`issue` writes and flushes but never commits (ADR-0021); `deliver` is a separate call because the route commits in between: a job
must never carry a code the database does not hold. The code is stored only as an Argon2 hash (ADR-0028) and is valid for two minutes.
"""

import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utc_now
from app.core.hashing import hash_secret, verify_secret
from app.models import AccountIdentity
from app.services.account import AccountService
from app.services.notifier import NotifierService, NotifierType

OTP_TTL = timedelta(minutes=2)
_CODE_DIGITS = 6


def generate_code() -> str:
    """A uniformly random 6-digit code, 100000 to 999999 (never a leading zero, as in the Node base)."""
    low = 10 ** (_CODE_DIGITS - 1)
    return str(low + secrets.randbelow(9 * low))


@dataclass(frozen=True)
class IssuedOtp:
    account_id: str
    # repr=False: a dataclass repr lands in logs and tracebacks, and the code must not (rules D8, P4).
    code: str = field(repr=False)


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

    @staticmethod
    async def verify_code(code: str, otp_hash: str) -> bool:
        """Whether `code` matches a stored `otpHash`. The expiry is the caller's check (task 7.2)."""
        return await verify_secret(code, otp_hash)
