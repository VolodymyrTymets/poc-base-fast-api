"""PasswordAuthService: sign up with an email and a password, check a password for sign-in (`find_credential`, `check`), change it (`find_credential_for_account`, `change`)
and recover it (`issue_reset_token`, `deliver_reset_token`, `find_reset_challenge`, `reset`). Ports the Node `JwtAuthStrategyService`.
Tasks: 7.3, 7.5, 7.6. ADR-0021, ADR-0026, ADR-0027, ADR-0028.

It writes and flushes but never commits (ADR-0021); the route commits after the tokens are issued. The sign-in check is two calls because the route ends the read transaction between them: Argon2 must not run with a pooled connection held (as in `OtpService`).
The password is stored as an Argon2id hash
(ADR-0028, which supersedes the bcrypt of the Node base) and `AccountIdentity.salt` stays null: the salt is inside the hash string.
"""

import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utc_now, violated_index
from app.core.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidResetTokenError,
)
from app.core.hashing import DUMMY_HASH, hash_secret, hash_token, verify_secret
from app.models import Account, AccountIdentity, AccountProfile
from app.services.account import AccountService
from app.services.account_profile import EMAIL_UNIQUE_INDEX
from app.services.notifier import NotifierService, NotifierType

# How long a reset token works (ENDPOINTS.md `restorePassword`); a new request replaces a live token.
RESET_TOKEN_TTL = timedelta(minutes=30)


def _credential_replacement(new_hash: str) -> dict[str, Any]:
    """The columns a new password sets, with everything issued under the old one cleared in the same UPDATE.

    The refresh token, a pending reset token and a pending sign-in code stop working; `salt` stays null because the salt is inside the Argon2 string (ADR-0028).
    """
    return {
        "hash": new_hash,
        "salt": None,
        "refresh_token": None,
        "reset_token_hash": None,
        "reset_token_expires_at": None,
        "otp_hash": None,
        "otp_salt": None,
        "otp_expires_at": None,
    }


@dataclass(frozen=True)
class IssuedReset:
    account_id: str
    # repr=False: a dataclass repr lands in logs and tracebacks, and the token must not (rules D8, P4).
    token: str = field(repr=False)


@dataclass(frozen=True)
class ResetChallenge:
    """What `find_reset_challenge` read: plain values, so it stays valid after the session's transaction ends. Both `None` when the token cannot be used."""

    identity_id: str | None
    # repr=False: the token's hash must not land in logs or tracebacks (rules D8, P4).
    token_hash: str | None = field(repr=False)


@dataclass(frozen=True)
class PasswordCredential:
    """What `find_credential` read: plain values, no ORM object, so it stays valid after the session's transaction ends."""

    account_id: str | None
    # repr=False: the stored hash must not land in logs or tracebacks (rules D8, P4). `None` when no password can be checked.
    password_hash: str | None = field(repr=False)


class PasswordAuthService:
    def __init__(
        self,
        session: AsyncSession,
        accounts: AccountService,
        notifier: NotifierService,
    ) -> None:
        self._session = session
        self._accounts = accounts
        self._notifier = notifier

    async def sign_up(self, email: str, password: str) -> str:
        """A `CUSTOMER` account with this email and password; returns its id. The caller commits, then issues tokens.

        `email` is already normalised and `password` already validated (`SignUpInput`). An email on any profile, a soft-deleted one included
        (its email stays reserved), is `EmailAlreadyRegisteredError`; so is losing a race on the unique index.
        """
        # Hash before the first query: this endpoint is unauthenticated, and an await on the hash thread pool with a transaction already
        # open would hold a pooled connection for every queued request (a flood would starve the authenticated routes of connections).
        password_hash = await hash_secret(password)

        # No `deleted` filter: the unique index spans every row, so a soft-deleted profile still owns its email.
        taken = await self._session.scalar(
            select(AccountProfile.id).where(AccountProfile.email == email).limit(1)
        )
        if taken is not None:
            raise EmailAlreadyRegisteredError

        try:
            # A savepoint, as in `AccountProfileService.update`: a failed flush must not poison the caller's transaction.
            async with self._session.begin_nested():
                account = await self._accounts.create_password_account(
                    email, password_hash
                )
        except IntegrityError as error:
            # Two sign-ups can both pass the check above; the unique index decides, and the loser gets the same answer.
            if violated_index(error) == EMAIL_UNIQUE_INDEX:
                raise EmailAlreadyRegisteredError from None
            raise
        return account.id

    async def find_credential(self, email: str) -> PasswordCredential:
        """The password hash of the live account with this email; nothing to check against for every other case.

        An unknown email, a soft-deleted account, profile or identity, and an OTP-only account (no hash) all read the same.
        """
        row = (
            await self._session.execute(
                select(Account.id, AccountIdentity.hash)
                .join(AccountProfile, AccountProfile.account_id == Account.id)
                .join(AccountIdentity, AccountIdentity.account_id == Account.id)
                .where(
                    AccountProfile.email == email,
                    AccountProfile.deleted.is_(False),
                    Account.deleted.is_(False),
                    AccountIdentity.deleted.is_(False),
                    AccountIdentity.hash.is_not(None),
                )
                .limit(1)
            )
        ).first()
        if row is None:
            return PasswordCredential(None, None)
        return PasswordCredential(row.id, row.hash)

    @staticmethod
    async def check(credential: PasswordCredential, password: str) -> str:
        """The account id when `password` matches the credential's hash; otherwise `InvalidCredentialsError`. Touches no database.

        Every failure is the same error (never `UnauthorizedError`, which makes a client refresh), and every path runs one Argon2 check, against a
        dummy hash when there is nothing to match, so the 401 timing does not reveal which emails are registered.
        """
        matches = await verify_secret(password, credential.password_hash or DUMMY_HASH)
        if (
            credential.account_id is None
            or credential.password_hash is None
            or not matches
        ):
            raise InvalidCredentialsError
        return credential.account_id

    async def find_credential_for_account(self, account_id: str) -> PasswordCredential:
        """The password hash of this live account, for a caller already authenticated by token; nothing to check against otherwise.

        A soft-deleted account or identity and an OTP-only account (no hash) all read the same (assumption A2, A3 of POC-7.5).
        """
        row = (
            await self._session.execute(
                select(Account.id, AccountIdentity.hash)
                .join(AccountIdentity, AccountIdentity.account_id == Account.id)
                .where(
                    Account.id == account_id,
                    Account.deleted.is_(False),
                    AccountIdentity.deleted.is_(False),
                    AccountIdentity.hash.is_not(None),
                )
            )
        ).first()
        if row is None:
            return PasswordCredential(None, None)
        return PasswordCredential(row.id, row.hash)

    async def change(
        self, credential: PasswordCredential, current_password: str, new_password: str
    ) -> None:
        """Replace the password after checking the current one, and end every session and pending credential. The caller commits.

        The check is inside, so no caller can change a password without it. Both Argon2 steps run before this transaction's first query, so the
        caller must have ended the read that found `credential` (as `sign_in` does). The write is conditional on the hash that was checked: a change
        or a reset that landed in between matches no row, and this one fails like a wrong password instead of overwriting it.
        """
        await self.check(credential, current_password)
        new_hash = await hash_secret(new_password)
        if credential.account_id is None or credential.password_hash is None:
            # `check` has already raised for these; this keeps the types honest and fails closed.
            raise InvalidCredentialsError
        # One UPDATE: the new hash and the revocation of everything issued under the old password (`_credential_replacement`).
        changed = await self._session.scalar(
            update(AccountIdentity)
            .where(
                AccountIdentity.account_id == credential.account_id,
                AccountIdentity.hash == credential.password_hash,
                AccountIdentity.deleted.is_(False),
                exists().where(
                    Account.id == credential.account_id, Account.deleted.is_(False)
                ),
            )
            .values(**_credential_replacement(new_hash))
            .returning(AccountIdentity.id)
        )
        if changed is None:
            raise InvalidCredentialsError
        await self._session.flush()

    async def issue_reset_token(self, email: str) -> IssuedReset | None:
        """A new reset token for the live account with this email, `None` for every other email. The caller commits, then calls `deliver_reset_token`.

        Unknown, soft-deleted (profile, account or identity) and well-formed-but-unregistered emails read the same, so the route answers all of them alike. A live
        token is replaced. An OTP-only account has no identity row yet and gets one: that is how it sets a first password. `email` is already normalised (`Email`).
        """
        account_id = await self._session.scalar(
            select(Account.id)
            .join(AccountProfile, AccountProfile.account_id == Account.id)
            .where(
                AccountProfile.email == email,
                AccountProfile.deleted.is_(False),
                Account.deleted.is_(False),
                # An account with no identity row passes; a soft-deleted identity is never revived by a reset.
                ~exists().where(
                    AccountIdentity.account_id == Account.id,
                    AccountIdentity.deleted.is_(True),
                ),
            )
            .limit(1)
        )
        if account_id is None:
            return None
        token = secrets.token_hex(32)
        # One statement, not select-then-insert: the identity may not exist yet and two requests may race on it. Only the reset columns are set on
        # conflict, so a password, a sign-in code and a refresh hash on the same identity survive (the table has no `updatedAt`).
        statement = insert(AccountIdentity).values(
            account_id=account_id,
            reset_token_hash=hash_token(token),
            reset_token_expires_at=utc_now() + RESET_TOKEN_TTL,
        )
        columns = AccountIdentity.__table__.c
        stored = await self._session.scalar(
            statement.on_conflict_do_update(
                index_elements=[columns.accountId],
                set_={
                    columns.resetTokenHash: statement.excluded[
                        columns.resetTokenHash.name
                    ],
                    columns.resetTokenExpiresAt: statement.excluded[
                        columns.resetTokenExpiresAt.name
                    ],
                },
                # An identity soft-deleted since the read above gets no token: no row comes back.
                where=columns.deleted.is_(False),
            ).returning(AccountIdentity.id)
        )
        if stored is None:
            return None
        await self._session.flush()
        return IssuedReset(account_id, token)

    async def deliver_reset_token(self, issued: IssuedReset | None) -> None:
        """Queue the email job for an issued token; `None` (an unknown email) does nothing. A queue that is down is logged by the notifier, not raised (ADR-0027)."""
        if issued is None:
            return
        await self._notifier.notify_about_password_reset(
            issued.account_id, issued.token, [NotifierType.EMAIL]
        )

    async def find_reset_challenge(self, token: str) -> ResetChallenge:
        """Read whether `token` names a live, unexpired reset token; an empty challenge for unknown, used, expired and soft-deleted alike."""
        token_hash = hash_token(token)
        identity_id = await self._session.scalar(
            select(AccountIdentity.id)
            .join(Account, Account.id == AccountIdentity.account_id)
            .where(
                AccountIdentity.reset_token_hash == token_hash,
                AccountIdentity.reset_token_expires_at > utc_now(),
                AccountIdentity.deleted.is_(False),
                Account.deleted.is_(False),
            )
        )
        if identity_id is None:
            return ResetChallenge(None, None)
        return ResetChallenge(identity_id, token_hash)

    async def reset(self, challenge: ResetChallenge, new_password: str) -> None:
        """Set a new password with a reset token that `find_reset_challenge` accepted, and end every session. The caller commits.

        An empty challenge is rejected before any hashing, so a garbage token costs no Argon2 work on this unauthenticated path. The Argon2 step runs before this
        transaction's first query, so the caller must have ended the read that found the challenge (as `sign_in` does). The write is conditional on the token
        still being there and unexpired: of two resets with one token, only the one that clears it changes the password. Every failure is `InvalidResetTokenError`.
        """
        if challenge.identity_id is None or challenge.token_hash is None:
            raise InvalidResetTokenError
        new_hash = await hash_secret(new_password)
        changed = await self._session.scalar(
            update(AccountIdentity)
            .where(
                AccountIdentity.id == challenge.identity_id,
                AccountIdentity.reset_token_hash == challenge.token_hash,
                AccountIdentity.reset_token_expires_at > utc_now(),
                AccountIdentity.deleted.is_(False),
                exists().where(
                    Account.id == AccountIdentity.account_id,
                    Account.deleted.is_(False),
                ),
            )
            .values(**_credential_replacement(new_hash))
            .returning(AccountIdentity.id)
        )
        if changed is None:
            raise InvalidResetTokenError
        await self._session.flush()
