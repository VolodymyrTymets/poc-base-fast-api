"""POST /api/v1/auth/refresh over HTTP on a real database. Task: 7.4 (ports `refresh-token.e2e-spec.ts`).

The request has its own session, so rows are read and changed through `db_engine`; they stay for the module, so each test uses an address of its own.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from time_machine import TimeMachineFixture
from utils.auth import AuthTokens, sign_in, sign_up
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.logging import JsonFormatter
from app.main import create_app
from app.models import Account, AccountIdentity, AccountProfile

REFRESH_PATH = "/api/v1/auth/refresh"
ACCOUNT_PATH = "/api/v1/account"
PHRASE = "correct-horse-battery"
UNAUTHORIZED = {
    "error": {
        "code": "UNAUTHORIZED",
        "message": "Authentication required",
        "details": [],
    }
}


def make_app(database_url: str) -> FastAPI:
    return create_app(
        Settings(
            app_env="test",
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )


def unique_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


def with_refresh_token(token: str) -> dict[str, str]:
    return {"x-refresh-token": token}


async def stored_refresh_hash(engine: AsyncEngine, email: str) -> str | None:
    async with engine.connect() as connection:
        return await connection.scalar(
            select(AccountIdentity.refresh_token)
            .join(
                AccountProfile, AccountProfile.account_id == AccountIdentity.account_id
            )
            .where(AccountProfile.email == email)
        )


async def test_refresh_gives_a_new_pair_and_stores_the_hash_of_the_new_refresh_token(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)

        response = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)
        body = response.json()
        account = await client.get(
            ACCOUNT_PATH, headers={"Authorization": f"Bearer {body['accessToken']}"}
        )

    stored = await stored_refresh_hash(db_engine, email)
    assert (
        response.status_code,
        sorted(body),
        body["refreshToken"] != tokens.refresh_token,
        account.status_code,
    ) == (200, ["accessToken", "refreshToken"], True, 200)
    assert stored == hashlib.sha256(body["refreshToken"].encode()).hexdigest()


async def test_the_old_refresh_token_is_rejected_after_a_refresh_and_the_new_one_works(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        first = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)

        replayed = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)
        renewed = await client.post(
            REFRESH_PATH, headers=with_refresh_token(first.json()["refreshToken"])
        )

    assert (replayed.status_code, replayed.json(), renewed.status_code) == (
        401,
        UNAUTHORIZED,
        200,
    )


async def test_an_older_refresh_token_is_rejected_after_a_newer_sign_in(
    module_database_url: str,
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        first = await sign_up(client, email, PHRASE)
        await sign_in(client, email, PHRASE)

        response = await client.post(REFRESH_PATH, headers=first.refresh_headers)

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)


def tampered(token: str) -> str:
    return token[:-2] + ("AA" if not token.endswith("AA") else "BB")


@pytest.mark.parametrize(
    "case", ["missing", "empty", "garbage", "tampered", "access-token"]
)
async def test_a_bad_refresh_token_is_401_unauthorized(
    module_database_url: str, case: str
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        headers: dict[str, dict[str, str]] = {
            "missing": {},
            "empty": with_refresh_token(""),
            "garbage": with_refresh_token("garbage"),
            "tampered": with_refresh_token(tampered(tokens.refresh_token)),
            "access-token": with_refresh_token(tokens.access_token),
        }

        response = await client.post(REFRESH_PATH, headers=headers[case])

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)


async def test_an_expired_refresh_token_is_401_unauthorized(
    module_database_url: str, frozen_clock: TimeMachineFixture
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        # The default refresh lifetime is 7 days.
        frozen_clock.shift(timedelta(days=8))

        response = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)


async def test_a_soft_deleted_account_cannot_refresh(
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

        response = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)


async def test_two_parallel_refreshes_with_one_token_give_one_200_and_one_401(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)

        first, second = await asyncio.gather(
            client.post(REFRESH_PATH, headers=tokens.refresh_headers),
            client.post(REFRESH_PATH, headers=tokens.refresh_headers),
        )

    winner = first if first.status_code == 200 else second
    stored = await stored_refresh_hash(db_engine, email)
    assert sorted([first.status_code, second.status_code]) == [200, 401]
    assert stored == hashlib.sha256(winner.json()["refreshToken"].encode()).hexdigest()


async def test_refresh_logs_no_token(
    module_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens: AuthTokens = await sign_up(client, unique_email(), PHRASE)
        caplog.set_level(logging.DEBUG)
        rotated = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)
        await client.post(REFRESH_PATH, headers=tokens.refresh_headers)

    output = _formatted(caplog)
    body: Any = rotated.json()
    leaked = [
        token
        for token in (
            tokens.access_token,
            tokens.refresh_token,
            body["accessToken"],
            body["refreshToken"],
        )
        if token in output
    ]
    assert leaked == []


def _formatted(caplog: pytest.LogCaptureFixture) -> str:
    formatter = JsonFormatter()
    return "\n".join(formatter.format(record) for record in caplog.records)
