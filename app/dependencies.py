"""Shared FastAPI dependencies: the current account from the Bearer token, the refresh account, and require_roles. Tasks: 4.4, 5.2.

Task 4.4 builds the two token dependencies. They verify the token only and return its claims;
loading the account (and rejecting a deleted one) comes with task 5.3, the refresh-hash check with
task 7.4, `require_roles` with task 5.2.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.core.errors import UnauthorizedError
from app.core.security import TokenClaims, TokenType, verify_token

REFRESH_HEADER_NAME = "x-refresh-token"

# auto_error=False: the schemes would answer 401/403 with their own body, and the contract
# body is built by the error handlers instead.
_bearer = HTTPBearer(auto_error=False, description="Access token from sign-in")
_refresh_header = APIKeyHeader(
    name=REFRESH_HEADER_NAME, auto_error=False, description="Refresh token"
)


def app_settings(request: Request) -> Settings:
    """The settings the app was built with (`create_app` stores them), not a second read of the environment."""
    settings: Settings = request.app.state.settings
    return settings


async def current_account(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(app_settings)],
) -> TokenClaims:
    """The account named by a valid access token in `Authorization: Bearer`; otherwise 401 UNAUTHORIZED."""
    # An HTTPException, not UnauthorizedError: its handler keeps the headers, and a 401
    # must say which scheme to use (RFC 9110).
    challenge = {"WWW-Authenticate": "Bearer"}
    if credentials is None:
        raise HTTPException(status_code=401, headers=challenge)
    try:
        return verify_token(settings, credentials.credentials, TokenType.ACCESS)
    except UnauthorizedError:
        raise HTTPException(status_code=401, headers=challenge) from None


async def refresh_account(
    token: Annotated[str | None, Depends(_refresh_header)],
    settings: Annotated[Settings, Depends(app_settings)],
) -> TokenClaims:
    """The account named by a valid refresh token in `x-refresh-token`; otherwise 401 UNAUTHORIZED.

    The token is not yet compared with the stored hash: that is `POST /auth/refresh` (task 7.4).
    """
    if not token:
        raise UnauthorizedError
    return verify_token(settings, token, TokenType.REFRESH)
