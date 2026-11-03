"""Creates the two account roles. Ports the Node `InitRolesMigration`. Task: 5.1."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountRole, AccountRoleType


class InitRoles:
    # Kept from the Node base (`init.roles.migration`, without the suffix), so the history of a database that
    # moves between the two bases reads the same.
    name = "init.roles"

    async def needs_to_run(self, session: AsyncSession) -> bool:
        # Any row counts, a soft-deleted one too: the table is not empty, so nothing is created behind it.
        return await session.scalar(select(AccountRole.id).limit(1)) is None

    async def run(self, session: AsyncSession) -> None:
        # The enum is the list: a role added to `AccountRoleType` is seeded without touching this file.
        session.add_all(AccountRole(type=role) for role in AccountRoleType)
