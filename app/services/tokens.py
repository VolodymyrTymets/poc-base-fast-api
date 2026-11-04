"""TokenService: issue the access and refresh token pair and store the refresh token's sha256. Ports the Node `JwtStrategyService.refreshTokens`.
Tasks: 7.2 (7.3 sign-up and sign-in, 7.4 refresh and 7.6 reset call `issue` too). ADR-0008, ADR-0021; rule P5.

`issue` writes and flushes but never commits (ADR-0021). Every call replaces the stored hash, so the previous refresh token stops
matching (rotation is real, unlike Node's bcrypt of the first 72 bytes). It proves nothing about the phone: `isPhoneVerified` is the
OTP service's to set.
"""

from dataclasses import dataclass, field

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.hashing import hash_token
from app.core.security import TokenType, issue_token
from app.models import AccountIdentity


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
