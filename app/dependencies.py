"""Shared FastAPI dependencies: the current account from the Bearer token, the refresh account, require_roles and one provider per service. Tasks: 4.4, 5.2, 6.1, I.9.

Task 4.4 builds the two token dependencies. They verify the token only and return its claims;
loading the account (and rejecting a deleted one) is done by the route that needs it, as `GET /account` does
(task 5.3, ADR-0022); the refresh-hash check comes with task 7.4. Task 5.2 adds `require_roles`, the role layer of rule P7.
Issue I.9 adds the service providers (ADR-0025): a route never builds a service, it takes `Depends(get_x_service)`, so a test can
swap one through `dependency_overrides` and a request shares one session (`get_session` is cached per request).
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.db import get_session
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.queue import QueueClient
from app.core.security import TokenClaims, TokenType, verify_token
from app.models import AccountRoleType
from app.services.account import AccountService
from app.services.account_profile import AccountProfileService
from app.services.account_role import AccountRoleService
from app.services.file_assert import FileAssertService

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


def get_queue(request: Request) -> QueueClient:
    """The queue a route or service enqueues jobs on (task 6.1); tests override it with `FakeQueue`."""
    queue: QueueClient = request.app.state.queue
    return queue


def get_account_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccountService:
    """The `AccountService` on the request's session (ADR-0025)."""
    return AccountService(session)


def get_account_role_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccountRoleService:
    """The `AccountRoleService` on the request's session (ADR-0025)."""
    return AccountRoleService(session)


def get_file_assert_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(app_settings)],
) -> FileAssertService:
    """The `FileAssertService` on the request's session, with the upload limits of the app's settings (ADR-0025)."""
    return FileAssertService(session, settings)


def get_account_profile_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    file_assert: Annotated[FileAssertService, Depends(get_file_assert_service)],
) -> AccountProfileService:
    """The `AccountProfileService`; its `FileAssertService` is a provider too, so a test may replace either (ADR-0025)."""
    return AccountProfileService(session, file_assert)


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


def require_roles(
    *roles: AccountRoleType,
) -> Callable[..., Awaitable[TokenClaims]]:
    """A dependency that admits an account holding at least one of `roles`; 401 without a valid token, else 403 FORBIDDEN.

    Use it as `Depends(require_roles(AccountRoleType.ADMIN))`. It returns the caller's claims, so a route
    that needs the id does not also depend on `current_account`.
    """
    if not roles:
        # Fail closed. The Node guard logged "no roles" and let the request through.
        raise ValueError("require_roles needs at least one role")
    allowed = frozenset(roles)

    async def guard(
        # Listed before the session so that an unauthenticated request is a 401 even with no database.
        claims: Annotated[TokenClaims, Depends(current_account)],
        role_service: Annotated[AccountRoleService, Depends(get_account_role_service)],
    ) -> TokenClaims:
        held = await role_service.get_account_roles(claims.account_id)
        if allowed.isdisjoint(held):
            raise ForbiddenError
        return claims

    return guard
