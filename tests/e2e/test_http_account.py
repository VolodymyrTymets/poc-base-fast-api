"""GET /api/v1/account over HTTP on a real database. Task: 5.3.

Rows are committed through `db_engine` because the request has its own session; they stay for the module,
so every test makes its own account.
"""

import uuid

from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.db import create_session_factory
from app.core.security import TokenType, issue_token
from app.main import create_app
from app.models import Account
from app.services.account import AccountService

PATH = "/api/v1/account"
BEARER = "Bearer"
IDENTITY_KEYS = {"hash", "salt", "otpHash", "otpSalt", "refreshToken", "resetTokenHash"}


def make_app(database_url: str | None) -> FastAPI:
    return create_app(
        Settings(
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )


def token_for(account_id: str) -> dict[str, str]:
    settings = Settings(jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY)
    return {
        "Authorization": f"Bearer {issue_token(settings, account_id, TokenType.ACCESS)}"
    }


async def password_account(db_engine: AsyncEngine) -> tuple[str, str]:
    email = f"{uuid.uuid4().hex}@example.com"
    async with create_session_factory(db_engine)() as session, session.begin():
        account = await AccountService(session).create_password_account(
            email, "secret-hash", "secret-salt"
        )
        return account.id, email


async def test_the_signed_in_account_is_returned_with_its_profile(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, email = await password_account(db_engine)

    async with running_client(make_app(module_database_url)) as client:
        response = await client.get(PATH, headers=token_for(account_id))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "createdAt", "updatedAt", "profile"}
    assert body["id"] == account_id
    assert body["profile"]["email"] == email
    assert set(body["profile"]) == {
        "id",
        "phoneNumber",
        "firstName",
        "lastName",
        "middleName",
        "dataOfBirth",
        "email",
        "isPhoneVerified",
    }


async def test_a_password_account_has_a_null_phone_number(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await password_account(db_engine)

    async with running_client(make_app(module_database_url)) as client:
        response = await client.get(PATH, headers=token_for(account_id))

    assert response.json()["profile"]["phoneNumber"] is None
    assert response.json()["profile"]["isPhoneVerified"] is False


async def test_no_identity_data_is_in_the_body(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await password_account(db_engine)

    async with running_client(make_app(module_database_url)) as client:
        response = await client.get(PATH, headers=token_for(account_id))

    assert not IDENTITY_KEYS & _keys(response.json())
    assert "secret-hash" not in response.text
    assert "secret-salt" not in response.text


async def test_a_token_of_an_unknown_account_is_unauthorized(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        response = await client.get(PATH, headers=token_for(str(uuid.uuid4())))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == BEARER


async def test_a_token_of_a_soft_deleted_account_is_unauthorized(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await password_account(db_engine)
    async with create_session_factory(db_engine)() as session, session.begin():
        await session.execute(
            update(Account).where(Account.id == account_id).values(deleted=True)
        )

    async with running_client(make_app(module_database_url)) as client:
        response = await client.get(PATH, headers=token_for(account_id))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == BEARER


async def test_no_token_is_unauthorized_without_a_database() -> None:
    async with running_client(make_app(None)) as client:
        response = await client.get(PATH)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == BEARER
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_a_tampered_token_is_unauthorized_without_a_database() -> None:
    async with running_client(make_app(None)) as client:
        response = await client.get(
            PATH, headers={"Authorization": "Bearer not.a.token"}
        )

    assert response.status_code == 401


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    return set()
