"""AccountRoleService: the roles an account holds, and giving it one. Ports the Node `AccountRoleService`. Tasks: 5.2.

The shape of a service (class over a session, flush but never commit) is ADR-0021.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Cache, NullReadCache
from app.models import AccountOnRole, AccountRole, AccountRoleType

# The cache model of a role read (ADR-0035).
ROLE_CACHE_MODEL = "AccountRole"


def _decode_roles(raw: object) -> list[AccountRoleType]:
    if isinstance(raw, list):
        return [AccountRoleType(item) for item in raw]
    # A ValueError is what `ReadCache` takes for an entry it cannot rebuild: a miss, not a crash.
    raise ValueError("cached roles are not a list")


class RoleNotFoundError(RuntimeError):
    """The role type has no `AccountRole` row: the base data was never seeded. A server fault, so a 500."""


class AccountRoleService:
    def __init__(self, session: AsyncSession, *, cache: Cache | None = None) -> None:
        self._session = session
        # Without a cache every read goes to the database: the write paths build the service this way (ADR-0035).
        self._cache: Cache = NullReadCache() if cache is None else cache

    async def get_account_roles(self, account_id: str) -> list[AccountRoleType]:
        """The role types the account holds, through the read cache (ADR-0035). A soft-deleted link or role does not count (rule P6).

        An empty list is not cached: an account with no role is the abnormal case, and a role added to it a moment later must show.
        Roles change only when an account is created, so nothing invalidates `ROLE_CACHE_MODEL` today; a future route that
        changes them must call `cache.invalidate` after its commit.
        """

        async def load() -> list[AccountRoleType] | None:
            return await self._load_roles(account_id) or None

        roles = await self._cache.get_or_load(
            ROLE_CACHE_MODEL,
            {"accountId": account_id},
            load,
            encode=lambda held: [role.value for role in held],
            decode=_decode_roles,
        )
        return roles or []

    async def _load_roles(self, account_id: str) -> list[AccountRoleType]:
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
