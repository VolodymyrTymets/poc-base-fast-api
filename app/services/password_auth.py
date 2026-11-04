"""PasswordAuthService: sign up with an email and a password (7.3), and check a password for sign-in (R2 of 7.3). Ports the Node `JwtAuthStrategyService`.
Tasks: 7.3 (7.5 change password and 7.6 reset call it too). ADR-0021, ADR-0027, ADR-0028.

It writes and flushes but never commits (ADR-0021); the route commits after the tokens are issued. The password is stored as an Argon2id hash
(ADR-0028, which supersedes the bcrypt of the Node base) and `AccountIdentity.salt` stays null: the salt is inside the hash string.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import violated_index
from app.core.errors import EmailAlreadyRegisteredError
from app.core.hashing import hash_secret
from app.models import AccountProfile
from app.services.account import AccountService
from app.services.account_profile import EMAIL_UNIQUE_INDEX


class PasswordAuthService:
    def __init__(self, session: AsyncSession, accounts: AccountService) -> None:
        self._session = session
        self._accounts = accounts

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
