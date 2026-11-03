"""PATCH /accounts/{accountId}/profile. Tasks: 5.4."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.db import get_session
from app.core.security import TokenClaims
from app.dependencies import app_settings, require_roles
from app.models import AccountRoleType
from app.schemas.account_profile import (
    AccountProfileResponse,
    UpdateAccountProfileInput,
)
from app.services.account_profile import AccountProfileService
from app.services.file_assert import FileAssertService

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
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(app_settings)],
) -> AccountProfileResponse:
    """Update the caller's own profile: only the fields sent change, `null` clears one."""
    service = AccountProfileService(session, FileAssertService(session, settings))
    profile = await service.update(claims.account_id, account_id, body)
    await session.commit()
    return AccountProfileResponse.model_validate(profile)
