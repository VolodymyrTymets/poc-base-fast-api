"""AccountRoleService: the roles an account holds, and giving it one. Ports the Node `AccountRoleService`. Tasks: 5.2.

The shape of a service (class over a session, flush but never commit) is ADR-0021.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountOnRole, AccountRole, AccountRoleType


class RoleNotFoundError(RuntimeError):
    """The role type has no `AccountRole` row: the base data was never seeded. A server fault, so a 500."""


class AccountRoleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_account_roles(self, account_id: str) -> list[AccountRoleType]:
        """The role types the account holds. A soft-deleted link or role does not count (rule P6)."""
        rows = await self._session.scalars(
            select(AccountRole.type)
            .join(AccountOnRole, AccountOnRole.role_id == AccountRole.id)
            .where(
                AccountOnRole.account_id == account_id,
                AccountOnRole.deleted.is_(False),
                AccountRole.deleted.is_(False),
            )
        )
        return list(rows)

    async def add_account_to_role(
        self, account_id: str, role_type: AccountRoleType
    ) -> AccountOnRole:
        """Link the account to the role of this type and flush; the caller commits (ADR-0021).

        Raises `RoleNotFoundError` for a type with no live role. Adding a role the account already has
        (even through a soft-deleted link) fails on the primary key, as the Node base did.
        """
        role = await self._session.scalar(
            select(AccountRole).where(
                AccountRole.type == role_type, AccountRole.deleted.is_(False)
            )
        )
        if role is None:
            raise RoleNotFoundError(f"Role {role_type} not found")
        link = AccountOnRole(account_id=account_id, role_id=role.id)
        self._session.add(link)
        await self._session.flush()
        return link
