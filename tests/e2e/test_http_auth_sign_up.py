"""POST /api/v1/auth/sign-up over HTTP on a real database. Task: 7.3 (ports `sign-up.e2e-spec.ts`).

The request has its own session, so rows are read through `db_engine`; they stay for the module, so each test uses an address of its own.
"""

import hashlib
import logging
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.hashing import verify_secret
from app.core.logging import JsonFormatter
from app.core.security import TokenType, verify_token
from app.main import create_app
from app.models import AccountIdentity, AccountProfile

SIGN_UP_PATH = "/api/v1/auth/sign-up"
ACCOUNT_PATH = "/api/v1/account"
PHRASE = "correct-horse-battery"
ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"


def make_app(database_url: str) -> FastAPI:
    return create_app(
        Settings(
            app_env="test",
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )


def unique_email(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}@example.com"


async def stored(engine: AsyncEngine, email: str) -> Any:
    async with engine.connect() as connection:
        return (
            await connection.execute(
                select(
                    AccountIdentity.hash,
                    AccountIdentity.salt,
                    # Labelled: a Core row is keyed by the database column name ("refreshToken").
                    AccountIdentity.refresh_token.label("refresh_token"),
                    AccountProfile.email,
                )
                .join(
                    AccountProfile,
                    AccountProfile.account_id == AccountIdentity.account_id,
                )
                .where(AccountProfile.email == email)
            )
        ).one_or_none()


async def test_sign_up_registers_a_customer_and_the_access_token_opens_the_account(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        response = await client.post(
            SIGN_UP_PATH, json={"email": email.upper(), "password": PHRASE}
        )
        body = response.json()
        account = await client.get(
            ACCOUNT_PATH, headers={"Authorization": f"Bearer {body['accessToken']}"}
        )

    settings = Settings(
        app_env="test", jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY
    )
    access = verify_token(settings, body["accessToken"], TokenType.ACCESS)
    row = await stored(db_engine, email)
    assert (
        response.status_code,
        sorted(body),
        account.status_code,
        account.json()["id"] == access.account_id,
        account.json()["profile"]["email"],
    ) == (201, ["accessToken", "refreshToken"], 200, True, email)
    assert row is not None
    assert row.hash.startswith("$argon2id$")
    assert await verify_secret(PHRASE, row.hash)
    assert row.salt is None
    assert (
        row.refresh_token == hashlib.sha256(body["refreshToken"].encode()).hexdigest()
    )


async def test_sign_up_with_a_taken_email_in_other_case_is_409_and_adds_nothing(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        first = await client.post(
            SIGN_UP_PATH, json={"email": email, "password": PHRASE}
        )
        second = await client.post(
            SIGN_UP_PATH, json={"email": email.upper(), "password": "another-phrase"}
        )

    row = await stored(db_engine, email)
    assert (first.status_code, second.status_code) == (201, 409)
    assert second.json()["error"]["code"] == ALREADY_REGISTERED
    assert row is not None
    assert await verify_secret(PHRASE, row.hash)


async def test_sign_up_with_the_email_of_a_soft_deleted_profile_is_409(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        await client.post(SIGN_UP_PATH, json={"email": email, "password": PHRASE})
        async with db_engine.begin() as connection:
            await connection.execute(
                update(AccountProfile)
                .where(AccountProfile.email == email)
                .values(deleted=True)
            )

        response = await client.post(
            SIGN_UP_PATH, json={"email": email, "password": PHRASE}
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == ALREADY_REGISTERED


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "not-an-email", "password": PHRASE}, "email"),
        ({"email": "a@b", "password": PHRASE}, "email"),
        ({"email": "a@example.com", "password": "short"}, "password"),
        ({"email": "a@example.com", "password": "x" * 73}, "password"),
        ({"email": "a@example.com", "password": "ab\x00cdefgh"}, "password"),
        ({"email": "a@example.com", "password": PHRASE, "role": "ADMIN"}, "role"),
    ],
    ids=[
        "bad-email",
        "no-top-level-domain",
        "short-password",
        "password-over-72-bytes",
        "control-character",
        "unknown-key",
    ],
)
async def test_sign_up_rejects_a_bad_body_naming_the_field(
    module_database_url: str, body: dict[str, str], field: str
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        response = await client.post(SIGN_UP_PATH, json=body)

    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (422, "VALIDATION_FAILED")
    assert field in str(error["details"])


async def test_sign_up_logs_no_password_hash_token_or_email(
    module_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    email = unique_email("logcheck")
    caplog.set_level(logging.DEBUG)
    async with running_client(make_app(module_database_url)) as client:
        response = await client.post(
            SIGN_UP_PATH, json={"email": email, "password": PHRASE}
        )
        await client.post(SIGN_UP_PATH, json={"email": email, "password": PHRASE})

    formatter = JsonFormatter()
    output = "\n".join(formatter.format(record) for record in caplog.records)
    body = response.json()
    leaked = [
        secret
        for secret in (
            PHRASE,
            email,
            body["accessToken"],
            body["refreshToken"],
            "$argon2",
        )
        if secret in output
    ]
    assert leaked == []


async def test_no_pooled_connection_is_held_while_the_password_is_hashed(
    module_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The route is unauthenticated: a connection held through the Argon2 hash would let a flood of calls fill the pool.
    from app.core.hashing import hash_secret

    app = make_app(module_database_url)
    checked_out_during_hash: list[int] = []

    async def watching_hash_secret(secret: str) -> str:
        checked_out_during_hash.append(app.state.engine.pool.checkedout())
        return await hash_secret(secret)

    monkeypatch.setattr("app.services.password_auth.hash_secret", watching_hash_secret)
    async with running_client(app) as client:
        await client.post(
            SIGN_UP_PATH, json={"email": unique_email(), "password": PHRASE}
        )

    assert checked_out_during_hash == [0]


async def test_a_client_helper_signs_up_over_the_real_route(
    module_database_url: str,
) -> None:
    from utils.auth import sign_up

    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        account: httpx.Response = await client.get(ACCOUNT_PATH, headers=tokens.headers)

    assert account.status_code == 200
