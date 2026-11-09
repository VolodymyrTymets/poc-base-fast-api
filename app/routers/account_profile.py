"""PATCH /accounts/{accountId}/profile. Tasks: 5.4, 9.2."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Cache
from app.core.db import get_session
from app.core.security import TokenClaims
from app.dependencies import get_account_profile_service, get_read_cache, require_roles
from app.models import AccountRoleType
from app.schemas.account_profile import (
    AccountProfileResponse,
    UpdateAccountProfileInput,
)
from app.services.account import ACCOUNT_CACHE_MODEL
from app.services.account_profile import AccountProfileService

router = APIRouter(prefix="/accounts", tags=["account_profile"])


@router.patch("/{accountId}/profile", response_model=AccountProfileResponse)
async def update_account_profile(
    # The wire name is camelCase like every field of the contract (ENDPOINTS.md); the Python name stays snake_case.
    account_id: Annotated[str, Path(alias="accountId")],
    body: UpdateAccountProfileInput,
    # Authenticate, then the role (rule P7); the third layer, that the caller owns `account_id`, is the service's.
    claims: Annotated[
        TokenClaims,
        Depends(require_roles(AccountRoleType.ADMIN, AccountRoleType.CUSTOMER)),
    ],
    service: Annotated[AccountProfileService, Depends(get_account_profile_service)],
    # The same session the service uses (`get_session` is cached per request): the handler owns the commit (ADR-0021).
    session: Annotated[AsyncSession, Depends(get_session)],
    cache: Annotated[Cache, Depends(get_read_cache)],
) -> AccountProfileResponse:
    """Update the caller's own profile: only the fields sent change, `null` clears one."""
    profile = await service.update(claims.account_id, account_id, body)
    await session.commit()
    # After the commit, never before: a read in between would cache the old row again (ADR-0035). The account snapshot holds
    # the profile, so its entries go; a failed update (a 409, a 403) raised above and leaves them alone.
    await cache.invalidate(ACCOUNT_CACHE_MODEL)
    return AccountProfileResponse.model_validate(profile)
