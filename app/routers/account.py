"""GET /account. Tasks: 5.3."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import TokenClaims
from app.dependencies import current_account, get_account_service
from app.schemas.account import AccountResponse
from app.services.account import AccountService

router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_model=AccountResponse)
async def read_account(
    # Listed before the service so that a bad token is a 401 even with no database.
    claims: Annotated[TokenClaims, Depends(current_account)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> AccountResponse:
    """The caller's own account, read from the token: authentication is the only layer (ADR-0022)."""
    account = await service.get_snapshot(claims.account_id)
    if account is None:
        # The token is valid but no longer maps to a live account (ENDPOINTS decisions 2 and 16): the same 401
        # as `current_account`, with its Bearer challenge.
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return account
