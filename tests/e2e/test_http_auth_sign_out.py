"""POST /api/v1/auth/sign-out over HTTP on a real database. Task: 7.4.

The request has its own session, so rows are read and changed through `db_engine`; they stay for the module, so each test uses an address or phone of its own.
"""

import logging
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from utils.auth import sign_up
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY
from utils.queue import FakeQueue

from app.config import Settings
from app.core.logging import JsonFormatter
from app.dependencies import get_queue
from app.main import create_app
from app.models import Account, AccountIdentity, AccountProfile

SIGN_OUT_PATH = "/api/v1/auth/sign-out"
REFRESH_PATH = "/api/v1/auth/refresh"
ACCOUNT_PATH = "/api/v1/account"
OTP_REQUEST_PATH = "/api/v1/auth/otp/request"
OTP_VERIFY_PATH = "/api/v1/auth/otp/verify"
PHRASE = "correct-horse-battery"
UNAUTHORIZED = {
    "error": {
        "code": "UNAUTHORIZED",
        "message": "Authentication required",
        "details": [],
    }
}


def make_app(database_url: str) -> FastAPI:
    app = create_app(
        Settings(
            app_env="test",
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )
    app.dependency_overrides[get_queue] = lambda: FakeQueue()
    return app


def unique_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def identity_of(engine: AsyncEngine, column: Any, where: Any) -> Any:
    async with engine.connect() as connection:
        return (
            await connection.execute(
                select(
                    AccountIdentity.hash,
                    AccountIdentity.refresh_token.label("refresh_token"),
                    AccountIdentity.otp_hash.label("otp_hash"),
                    AccountIdentity.otp_salt.label("otp_salt"),
                    AccountIdentity.otp_expires_at.label("otp_expires_at"),
                )
                .join(
                    AccountProfile,
                    AccountProfile.account_id == AccountIdentity.account_id,
                )
                .where(column == where)
            )
        ).one()


async def test_sign_out_answers_204_with_no_body_and_clears_the_refresh_hash_not_the_password(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)

        response = await client.post(SIGN_OUT_PATH, headers=tokens.headers)

    row = await identity_of(db_engine, AccountProfile.email, email)
    assert (response.status_code, response.content) == (204, b"")
    assert (row.refresh_token, row.hash is not None) == (None, True)


async def test_the_refresh_token_is_rejected_after_sign_out_and_the_access_token_still_works(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        await client.post(SIGN_OUT_PATH, headers=tokens.headers)

        refresh = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)
        account = await client.get(ACCOUNT_PATH, headers=tokens.headers)

    assert (refresh.status_code, refresh.json(), account.status_code) == (
        401,
        UNAUTHORIZED,
        200,
    )


@pytest.mark.parametrize("case", ["missing", "garbage", "refresh-token"])
async def test_sign_out_without_a_valid_access_token_is_401_unauthorized(
    module_database_url: str, case: str
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        headers: dict[str, dict[str, str]] = {
            "missing": {},
            "garbage": bearer("garbage"),
            "refresh-token": bearer(tokens.refresh_token),
        }

        response = await client.post(SIGN_OUT_PATH, headers=headers[case])
        still_refreshable = await client.post(
            REFRESH_PATH, headers=tokens.refresh_headers
        )

    assert (response.status_code, response.json()["error"]["code"]) == (
        401,
        "UNAUTHORIZED",
    )
    assert still_refreshable.status_code == 200


async def test_a_second_sign_out_is_204(module_database_url: str) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        first = await client.post(SIGN_OUT_PATH, headers=tokens.headers)

        second = await client.post(SIGN_OUT_PATH, headers=tokens.headers)

    assert (first.status_code, second.status_code) == (204, 204)


async def test_sign_out_of_a_soft_deleted_account_is_204(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)
        async with db_engine.begin() as connection:
            await connection.execute(
                update(Account)
                .where(
                    Account.id.in_(
                        select(AccountProfile.account_id).where(
                            AccountProfile.email == email
                        )
                    )
                )
                .values(deleted=True)
            )

        response = await client.post(SIGN_OUT_PATH, headers=tokens.headers)

    assert response.status_code == 204


async def test_a_sign_in_code_requested_before_sign_out_no_longer_verifies(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    phone = "+12125550174"
    async with running_client(make_app(module_database_url)) as client:
        first = await client.post(OTP_REQUEST_PATH, json={"phoneNumber": phone})
        signed_in = await client.post(
            OTP_VERIFY_PATH,
            json={"phoneNumber": phone, "code": first.json()["code"]},
        )
        pending = await client.post(OTP_REQUEST_PATH, json={"phoneNumber": phone})
        await client.post(
            SIGN_OUT_PATH, headers=bearer(signed_in.json()["accessToken"])
        )

        response = await client.post(
            OTP_VERIFY_PATH,
            json={"phoneNumber": phone, "code": pending.json()["code"]},
        )

    row = await identity_of(db_engine, AccountProfile.phone_number, phone)
    assert (response.status_code, response.json()["error"]["code"]) == (
        401,
        "INVALID_CREDENTIALS",
    )
    assert (row.otp_hash, row.otp_salt, row.otp_expires_at, row.refresh_token) == (
        None,
        None,
        None,
        None,
    )


async def test_sign_out_logs_no_token(
    module_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        caplog.set_level(logging.DEBUG)
        await client.post(SIGN_OUT_PATH, headers=tokens.headers)
        await client.post(SIGN_OUT_PATH, headers=bearer("garbage"))

    formatter = JsonFormatter()
    output = "\n".join(formatter.format(record) for record in caplog.records)
    leaked = [
        token
        for token in (tokens.access_token, tokens.refresh_token)
        if token in output
    ]
    assert leaked == []
