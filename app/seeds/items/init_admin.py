"""Creates the sample admin account. Ports the Node `InitAdminMigration`. Task: 5.5.

Development environments only (the registry): production gets no admin from this base (ADR-0023's ticket, spec Q3).
Differences from Node, on purpose: the check is by role type through the join, not `roleId == 'ADMIN'` (issue I.4); the phone
is a valid number in the range reserved for fiction (Node's `+11111111111` fails `phonenumbers`, so that admin could never ask for
an OTP); the last name is neutral.
"""

from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.db import utc_now
from app.models import (
    Account,
    AccountOnRole,
    AccountProfile,
    AccountRole,
    AccountRoleType,
)
from app.schemas.account_profile import UpdateAccountProfileInput
from app.services.account import AccountService
from app.services.account_profile import AccountProfileService
from app.services.account_role import AccountRoleService
from app.services.file_assert import FileAssertService


class SampleAdminPhoneInUseError(RuntimeError):
    """The sample admin's phone number already has an account, so the admin cannot be created without ambiguity."""


class AdminSample(TypedDict):
    phone_number: str
    email: str
    first_name: str
    last_name: str


# 555-0100 to 555-0199 is the NANP range reserved for fiction, so the number never belongs to a real person.
ADMINS: list[AdminSample] = [
    {
        "phone_number": "+12125550100",
        "email": "admin+d1@example.com",
        "first_name": "Admin",
        "last_name": "User",
    },
]


class InitAdmin:
    # The Node name without the `.migration` suffix, like `init.roles`.
    name = "init.admin"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def needs_to_run(self, session: AsyncSession) -> bool:
        # By role type: Node compared the role id with the string 'ADMIN', which never matches a uuid (issue I.4).
        holder = await session.scalar(
            select(Account.id)
            .join(AccountOnRole, AccountOnRole.account_id == Account.id)
            .join(AccountRole, AccountRole.id == AccountOnRole.role_id)
            .where(
                AccountRole.type == AccountRoleType.ADMIN,
                AccountRole.deleted.is_(False),
                AccountOnRole.deleted.is_(False),
                Account.deleted.is_(False),
            )
            .limit(1)
        )
        return holder is None

    async def run(self, session: AsyncSession) -> None:
        profiles = AccountProfileService(
            session, FileAssertService(session, self._settings)
        )
        for sample in ADMINS:
            # The phone has no unique index: a second account with it would make `get_by_phone` (the OTP sign-in of task 7.1)
            # reach the older one. Fail with a fixed message rather than create it or skip it silently (rule D5).
            if await AccountService(session).get_by_phone(sample["phone_number"]):
                raise SampleAdminPhoneInUseError(
                    "the sample admin phone already belongs to an account"
                )
            # WHY: AccountService._create always grants CUSTOMER, and an admin must not hold it; this follows that
            # method (task 5.3): the identity is set to None because an unset relationship cannot lazy-load on an
            # async session, and the role is added after the flush. A change to _create must revisit this.
            account = Account(last_login_at=utc_now())
            account.profile = AccountProfile(phone_number=sample["phone_number"])
            account.identity = None
            session.add(account)
            await session.flush()
            await AccountRoleService(session).add_account_to_role(
                account.id, AccountRoleType.ADMIN
            )
            await profiles.update(
                account.id,
                account.id,
                UpdateAccountProfileInput(
                    first_name=sample["first_name"],
                    last_name=sample["last_name"],
                    email=sample["email"],
                ),
            )
