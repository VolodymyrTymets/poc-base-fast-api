"""POST /api/v1/auth/sign-in over HTTP on a real database. Task: 7.3 (ports `sign-in.e2e-spec.ts`).

The request has its own session, so rows are read and changed through `db_engine`; they stay for the module, so each test uses an address of its own.
"""

import hashlib
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.hashing import verify_secret
from app.core.security import TokenType, verify_token
from app.main import create_app
from app.models import Account, AccountIdentity, AccountProfile

SIGN_UP_PATH = "/api/v1/auth/sign-up"
SIGN_IN_PATH = "/api/v1/auth/sign-in"
ACCOUNT_PATH = "/api/v1/account"
PHRASE = "correct-horse-battery"
INVALID_CREDENTIALS = {
    "error": {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid credentials",
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


async def refresh_hash_of(engine: AsyncEngine, email: str) -> str | None:
    async with engine.connect() as connection:
        return await connection.scalar(
            select(AccountIdentity.refresh_token)
            .join(
                AccountProfile, AccountProfile.account_id == AccountIdentity.account_id
            )
            .where(AccountProfile.email == email)
        )


async def test_sign_in_with_the_right_password_gives_tokens_that_open_the_account(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        await client.post(SIGN_UP_PATH, json={"email": email, "password": PHRASE})
        before = await refresh_hash_of(db_engine, email)

        response = await client.post(
            SIGN_IN_PATH, json={"email": email.upper(), "password": PHRASE}
        )
        body = response.json()
        account = await client.get(
            ACCOUNT_PATH, headers={"Authorization": f"Bearer {body['accessToken']}"}
        )

    settings = Settings(
        app_env="test", jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY
    )
    access = verify_token(settings, body["accessToken"], TokenType.ACCESS)
    after = await refresh_hash_of(db_engine, email)
    assert (
        response.status_code,
        sorted(body),
        account.status_code,
        account.json()["id"] == access.account_id,
    ) == (200, ["accessToken", "refreshToken"], 200, True)
    assert after == hashlib.sha256(body["refreshToken"].encode()).hexdigest()
    assert after != before


async def test_a_second_sign_in_replaces_the_refresh_hash_of_the_first(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        await client.post(SIGN_UP_PATH, json={"email": email, "password": PHRASE})
        first = (
            await client.post(SIGN_IN_PATH, json={"email": email, "password": PHRASE})
        ).json()
        second = (
            await client.post(SIGN_IN_PATH, json={"email": email, "password": PHRASE})
        ).json()

    stored = await refresh_hash_of(db_engine, email)
    assert stored == hashlib.sha256(second["refreshToken"].encode()).hexdigest()
    assert stored != hashlib.sha256(first["refreshToken"].encode()).hexdigest()


async def test_sign_in_keeps_the_password_hash_it_checked(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        await client.post(SIGN_UP_PATH, json={"email": email, "password": PHRASE})
        await client.post(SIGN_IN_PATH, json={"email": email, "password": PHRASE})

    async with db_engine.connect() as connection:
        stored = await connection.scalar(
            select(AccountIdentity.hash)
            .join(
                AccountProfile, AccountProfile.account_id == AccountIdentity.account_id
            )
            .where(AccountProfile.email == email)
        )
    assert stored is not None
    assert await verify_secret(PHRASE, stored)


async def test_sign_in_failures_are_one_401_body(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    registered = unique_email()
    otp_only = unique_email()
    deleted = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        await client.post(SIGN_UP_PATH, json={"email": registered, "password": PHRASE})
        await client.post(SIGN_UP_PATH, json={"email": deleted, "password": PHRASE})
        await client.post(
            "/api/v1/auth/otp/request", json={"phoneNumber": "+12125550173"}
        )
        async with db_engine.begin() as connection:
            await connection.execute(
                update(AccountProfile)
                .where(AccountProfile.phone_number == "+12125550173")
                .values(email=otp_only)
            )
            await connection.execute(
                update(Account)
                .where(
                    Account.id.in_(
                        select(AccountProfile.account_id).where(
                            AccountProfile.email == deleted
                        )
                    )
                )
                .values(deleted=True)
            )

        attempts = {
            "wrong-password": (registered, "not-the-phrase"),
            "unknown-email": (unique_email(), PHRASE),
            "otp-only-account": (otp_only, PHRASE),
            "soft-deleted-account": (deleted, PHRASE),
        }
        responses = {
            name: await client.post(
                SIGN_IN_PATH, json={"email": email, "password": password}
            )
            for name, (email, password) in attempts.items()
        }

    assert {name: (r.status_code, r.json()) for name, r in responses.items()} == {
        name: (401, INVALID_CREDENTIALS) for name in attempts
    }


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "not-an-email", "password": PHRASE}, "email"),
        ({"email": "a@example.com", "password": ""}, "password"),
        ({"email": "a@example.com", "password": "x" * 73}, "password"),
        ({"email": "a@example.com", "password": PHRASE, "role": "ADMIN"}, "role"),
    ],
    ids=["bad-email", "empty-password", "password-over-72-bytes", "unknown-key"],
)
async def test_sign_in_rejects_a_bad_body_naming_the_field(
    module_database_url: str, body: dict[str, str], field: str
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        response = await client.post(SIGN_IN_PATH, json=body)

    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (422, "VALIDATION_FAILED")
    assert field in str(error["details"])


@pytest.mark.parametrize("right_password", [True, False], ids=["right", "wrong"])
async def test_no_pooled_connection_is_held_while_the_password_is_checked(
    module_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    right_password: bool,
) -> None:
    # The route is unauthenticated: a connection held through the Argon2 check would let a flood of calls fill the pool.
    app = make_app(module_database_url)
    email = unique_email()
    checked_out_during_check: list[int] = []

    async def watching_verify_secret(secret: str, hashed: str) -> bool:
        checked_out_during_check.append(app.state.engine.pool.checkedout())
        return await verify_secret(secret, hashed)

    async with running_client(app) as client:
        await client.post(SIGN_UP_PATH, json={"email": email, "password": PHRASE})
        monkeypatch.setattr(
            "app.services.password_auth.verify_secret", watching_verify_secret
        )

        await client.post(
            SIGN_IN_PATH,
            json={
                "email": email,
                "password": PHRASE if right_password else "not-the-phrase",
            },
        )

    assert checked_out_during_check == [0]
