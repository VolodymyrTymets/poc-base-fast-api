"""require_roles over HTTP, on a real database: 401 before 403, and the roles decide. Task: 5.2.

Rows are committed through `db_engine` because the request has its own session on its own connection; they stay for
the module, so every test makes its own account.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.db import create_session_factory, get_session
from app.core.security import TokenClaims, TokenType, issue_token
from app.dependencies import require_roles
from app.main import create_app
from app.models import Account, AccountRoleType
from app.services.account_role import AccountRoleService

ADMIN = AccountRoleType.ADMIN
CUSTOMER = AccountRoleType.CUSTOMER
FORBIDDEN = {"error": {"code": "FORBIDDEN", "message": "Not allowed", "details": []}}


def make_app(database_url: str) -> FastAPI:
    app = create_app(
        Settings(
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )

    @app.get("/api/v1/_admin")
    async def admin_only(
        claims: Annotated[TokenClaims, Depends(require_roles(ADMIN))],
    ) -> dict[str, str]:
        return {"id": claims.account_id}

    @app.get("/api/v1/_any")
    async def either(
        claims: Annotated[TokenClaims, Depends(require_roles(ADMIN, CUSTOMER))],
    ) -> dict[str, str]:
        return {"id": claims.account_id}

    @app.post("/api/v1/_grant")
    async def grant(
        claims: Annotated[TokenClaims, Depends(require_roles(ADMIN))],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, str]:
        # The pattern of ADR-0021: the guard has already read on this session, and the handler commits.
        target = await _new_account(session)
        await AccountRoleService(session).add_account_to_role(target, CUSTOMER)
        await session.commit()
        return {"id": target}

    return app


async def account_with(db_engine: AsyncEngine, *roles: AccountRoleType) -> str:
    """Commit an account holding `roles`; the token for it comes from `token_for`."""
    async with create_session_factory(db_engine)() as session, session.begin():
        account_id = await _new_account(session)
        for role in roles:
            await AccountRoleService(session).add_account_to_role(account_id, role)
    return account_id


async def _new_account(session: AsyncSession) -> str:
    account = Account(last_login_at=datetime.now(UTC).replace(tzinfo=None))
    session.add(account)
    await session.flush()
    return account.id


def token_for(account_id: str) -> dict[str, str]:
    settings = Settings(jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY)
    token = issue_token(settings, account_id, TokenType.ACCESS)
    return {"Authorization": f"Bearer {token}"}


async def test_a_customer_is_forbidden_on_an_admin_route(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id = await account_with(db_engine, CUSTOMER)

    async with running_client(make_app(module_database_url)) as client:
        response = await client.get("/api/v1/_admin", headers=token_for(account_id))

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


async def test_an_admin_reaches_the_handler_with_their_claims(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id = await account_with(db_engine, ADMIN)

    async with running_client(make_app(module_database_url)) as client:
        response = await client.get("/api/v1/_admin", headers=token_for(account_id))

    assert response.status_code == 200
    assert response.json() == {"id": account_id}


async def test_either_role_passes_a_route_that_lists_both(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    admin = await account_with(db_engine, ADMIN)
    customer = await account_with(db_engine, CUSTOMER)

    async with running_client(make_app(module_database_url)) as client:
        as_admin = await client.get("/api/v1/_any", headers=token_for(admin))
        as_customer = await client.get("/api/v1/_any", headers=token_for(customer))

    assert (as_admin.status_code, as_customer.status_code) == (200, 200)


async def test_an_account_with_no_role_is_forbidden(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id = await account_with(db_engine)

    async with running_client(make_app(module_database_url)) as client:
        response = await client.get("/api/v1/_any", headers=token_for(account_id))

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


async def test_a_token_for_an_unknown_account_is_forbidden(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        response = await client.get(
            "/api/v1/_any",
            headers=token_for("33333333-3333-4333-8333-333333333333"),
        )

    # Rejecting a missing account is task 5.3; until then it holds no role, so the guard says 403.
    assert response.status_code == 403


async def test_no_token_is_unauthorized_not_forbidden(module_database_url: str) -> None:
    async with running_client(make_app(module_database_url)) as client:
        response = await client.get("/api/v1/_admin")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_no_token_is_unauthorized_even_without_a_database() -> None:
    app = create_app(
        Settings(
            database_url=None,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )

    @app.get("/api/v1/_admin")
    async def admin_only(
        claims: Annotated[TokenClaims, Depends(require_roles(ADMIN))],
    ) -> dict[str, Any]:
        return {}

    async with running_client(app) as client:
        response = await client.get("/api/v1/_admin")

    assert response.status_code == 401


async def test_a_guarded_route_can_write_and_commit_on_the_shared_session(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    admin = await account_with(db_engine, ADMIN)

    async with running_client(make_app(module_database_url)) as client:
        response = await client.post("/api/v1/_grant", headers=token_for(admin))

    assert response.status_code == 200
    async with create_session_factory(db_engine)() as session:
        roles = await AccountRoleService(session).get_account_roles(
            response.json()["id"]
        )
    assert roles == [CUSTOMER]
