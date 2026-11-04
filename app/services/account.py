"""AccountService: find an account by id or phone, create a customer or a password account. Ports the Node `AccountService`. Tasks: 5.3, 9.2.

The shape of a service (class over a session, flush but never commit) is ADR-0021. The password hash (and an optional salt)
come from the caller: `PasswordAuthService` (task 7.3) hashes, and this service adds no dependency for it.
"""

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import utc_now
from app.models import Account, AccountIdentity, AccountProfile, AccountRoleType
from app.services.account_role import AccountRoleService


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, account_id: str) -> Account | None:
        """The live account with its live profile loaded; `None` for an unknown or soft-deleted account (rule P6)."""
        result = await self._session.scalars(
            _live_accounts().where(Account.id == account_id)
        )
        return result.one_or_none()

    async def get_by_phone(self, phone_number: str) -> Account | None:
        """The oldest live account whose live profile has this phone number; `None` when there is none."""
        result = await self._session.scalars(
            _live_accounts()
            .join(
                AccountProfile,
                (AccountProfile.account_id == Account.id)
                & AccountProfile.deleted.is_(False),
            )
            .where(AccountProfile.phone_number == phone_number)
            # The phone has no unique index (as in Prisma): two concurrent first sign-ins can create two accounts.
            # The oldest wins, like Prisma's findFirst, instead of failing every later lookup.
            .order_by(Account.created_at, Account.id)
            .limit(1)
        )
        return result.first()

    async def create_customer(self, phone_number: str) -> Account:
        """A `CUSTOMER` account with a profile holding the phone number. Flushes; the caller commits (ADR-0021)."""
        return await self._create(AccountProfile(phone_number=phone_number))

    async def create_password_account(
        self, email: str, password_hash: str, password_salt: str | None = None
    ) -> Account:
        """A `CUSTOMER` account with a profile (email), a password identity and the role link, in the caller's transaction.

        The caller normalises the email (task 7.3). The salt is `None` for an Argon2 hash, which carries its own (ADR-0028). A second account with the same email fails on the unique
        index with `IntegrityError`; the caller rolls back, and nothing of this call remains.
        """
        return await self._create(
            AccountProfile(email=email),
            AccountIdentity(hash=password_hash, salt=password_salt),
        )

    async def _create(
        self, profile: AccountProfile, identity: AccountIdentity | None = None
    ) -> Account:
        account = Account(last_login_at=utc_now())
        account.profile = profile
        # Set even when None: an unset relationship would lazy-load on first access, which fails on an async session.
        account.identity = identity
        self._session.add(account)
        await self._session.flush()
        await AccountRoleService(self._session).add_account_to_role(
            account.id, AccountRoleType.CUSTOMER
        )
        return account


def _live_accounts() -> Select[Account]:
    # populate_existing: a profile soft-deleted earlier in the same session must not be served from the identity map.
    return (
        select(Account)
        .where(Account.deleted.is_(False))
        .options(selectinload(Account.profile.and_(AccountProfile.deleted.is_(False))))
        .execution_options(populate_existing=True)
    )
