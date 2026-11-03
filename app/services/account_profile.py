"""AccountProfileService: read and update an account's profile, with the ownership, avatar and email checks. Ports the Node `AccountProfileService`. Tasks: 5.4, 9.2.

The shape of a service (class over a session, flush but never commit) is ADR-0021. The ownership layer of rule P7 is here, not in
the router, so every caller of `update` gets it. The cache invalidation of the Node service waits for task 9.2.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EmailAlreadyRegisteredError, ForbiddenError, NotFoundError
from app.models import Account, AccountProfile
from app.schemas.account_profile import UpdateAccountProfileInput
from app.services.file_assert import FileAssertService

# The unique index of `AccountProfile.email`; the only unique column an update can hit (the account id is not changed).
EMAIL_UNIQUE_INDEX = "AccountProfile_email_key"


class AccountProfileService:
    def __init__(self, session: AsyncSession, file_assert: FileAssertService) -> None:
        self._session = session
        self._file_assert = file_assert

    async def get_by_account_id(self, account_id: str) -> AccountProfile | None:
        """The live profile of a live account; `None` when there is none (rule P6)."""
        result = await self._session.scalars(
            select(AccountProfile)
            .join(Account, Account.id == AccountProfile.account_id)
            .where(
                AccountProfile.account_id == account_id,
                AccountProfile.deleted.is_(False),
                Account.deleted.is_(False),
            )
            # A profile changed earlier in this session must be read back as stored.
            .execution_options(populate_existing=True)
        )
        return result.one_or_none()

    async def update(
        self,
        caller_id: str,
        account_id: str,
        changes: UpdateAccountProfileInput,
    ) -> AccountProfile:
        """Apply the fields that were sent to the caller's own profile and flush; the caller commits (ADR-0021).

        `ForbiddenError` when `caller_id` is not `account_id` (checked first, nothing is read), `NotFoundError` without a
        live profile, `ForbiddenError` for an avatar the caller did not create, `EmailAlreadyRegisteredError` for an email
        another profile holds. An explicit `None` clears a field; one that was not sent stays as it is.
        """
        if caller_id != account_id:
            raise ForbiddenError
        profile = await self.get_by_account_id(account_id)
        if profile is None:
            raise NotFoundError
        sent = changes.model_fields_set
        if changes.avatar_id is not None:
            await self._file_assert.get_owned_file(changes.avatar_id, account_id)
        try:
            # The savepoint comes first: entering it flushes pending changes, and a failed flush must not poison the
            # caller's transaction. By attribute name: the model's aliases are the wire names.
            async with self._session.begin_nested():
                for name in sent:
                    setattr(profile, name, getattr(changes, name))
                await self._session.flush()
        except IntegrityError as error:
            if _violated_index(error) == EMAIL_UNIQUE_INDEX:
                raise EmailAlreadyRegisteredError from None
            raise
        return profile


def _violated_index(error: IntegrityError) -> str | None:
    # SQLAlchemy wraps the driver's error; asyncpg's UniqueViolationError is its `__cause__` and carries the name.
    cause = error.orig.__cause__ if error.orig is not None else None
    name = getattr(cause, "constraint_name", None)
    return name if isinstance(name, str) else None
