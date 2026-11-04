"""TokenService: issue the access and refresh token pair and store the refresh token's sha256, rotate it on refresh and clear it on sign-out.
Ports the Node `JwtStrategyService.refreshTokens` and `validateRefreshToken` and `AuthService.signOut`.
Tasks: 7.2 (7.3 sign-up and sign-in and 7.6 reset call `issue` too), 7.4 (`rotate`, `revoke`). ADR-0008, ADR-0021; rule P5.

Every method writes and flushes but never commits (ADR-0021). Every call replaces the stored hash, so the previous refresh token stops
matching (rotation is real, unlike Node's bcrypt of the first 72 bytes). It proves nothing about the phone: `isPhoneVerified` is the
OTP service's to set.
"""

from dataclasses import dataclass, field

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import UnauthorizedError
from app.core.hashing import hash_token, token_matches
from app.core.security import TokenType, issue_token
from app.models import Account, AccountIdentity


@dataclass(frozen=True)
class TokenPair:
    # repr=False: a dataclass repr lands in logs and tracebacks, and a token must not (rules D8, P4).
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


class TokenService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def issue(self, account_id: str) -> TokenPair:
        """A new pair for `account_id`; the identity row is created when the account has none. The caller commits."""
        pair = TokenPair(
            access_token=issue_token(self._settings, account_id, TokenType.ACCESS),
            refresh_token=issue_token(self._settings, account_id, TokenType.REFRESH),
        )
        # One statement, not select-then-insert: the identity may not exist yet (an OTP-less account) and two requests may race on it.
        # Only the refresh column is set on conflict, so a password or an OTP on the same identity survives.
        statement = insert(AccountIdentity).values(
            account_id=account_id, refresh_token=hash_token(pair.refresh_token)
        )
        columns = AccountIdentity.__table__.c
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[columns.accountId],
                set_={
                    columns.refreshToken: statement.excluded[columns.refreshToken.name]
                },
            )
        )
        await self._session.flush()
        return pair

    async def rotate(self, account_id: str, presented_token: str) -> TokenPair:
        """A new pair in exchange for the refresh token the account last received; `UnauthorizedError` for any other token.

        The caller has verified the token's signature (`refresh_account`); this is the check against the stored hash. A signed-out account,
        one that signed in again since, a soft-deleted account or identity, and a token that lost a race all read the same: 401 UNAUTHORIZED.
        """
        stored = await self._session.scalar(
            select(AccountIdentity.refresh_token)
            .join(Account, Account.id == AccountIdentity.account_id)
            .where(
                AccountIdentity.account_id == account_id,
                AccountIdentity.deleted.is_(False),
                Account.deleted.is_(False),
            )
        )
        if stored is None or not token_matches(presented_token, stored):
            raise UnauthorizedError
        pair = TokenPair(
            access_token=issue_token(self._settings, account_id, TokenType.ACCESS),
            refresh_token=issue_token(self._settings, account_id, TokenType.REFRESH),
        )
        # Conditional on the hash just checked: a second request that presents the same token reads the same value, but only one UPDATE finds it
        # still in place (the other waits on the row lock, then matches nothing), so one refresh token never mints two sessions.
        swapped = await self._session.scalar(
            update(AccountIdentity)
            .where(
                AccountIdentity.account_id == account_id,
                AccountIdentity.refresh_token == stored,
                AccountIdentity.deleted.is_(False),
                # The account too: a soft-delete between the SELECT and this UPDATE must not get one last refresh.
                exists().where(Account.id == account_id, Account.deleted.is_(False)),
            )
            .values(refresh_token=hash_token(pair.refresh_token))
            .returning(AccountIdentity.id)
        )
        if swapped is None:
            raise UnauthorizedError
        await self._session.flush()
        return pair

    async def revoke(self, account_id: str) -> None:
        """End the account's session: clear the stored refresh hash and any pending sign-in code. The caller commits.

        Idempotent: an account with no identity row, or nothing stored, has nothing to clear and that is not an error. The password hash stays.
        """
        await self._session.execute(
            update(AccountIdentity)
            .where(AccountIdentity.account_id == account_id)
            .values(
                refresh_token=None, otp_hash=None, otp_salt=None, otp_expires_at=None
            )
        )
        await self._session.flush()
