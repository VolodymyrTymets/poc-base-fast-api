"""POST /api/v1/auth/password/change over HTTP on a real database. Task: 7.5 (ports `change-password.e2e-spec.ts`).

The request has its own session, so rows are read and changed through `db_engine`; they stay for the module, so each test uses an address or phone of its own.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from time_machine import TimeMachineFixture
from utils.auth import sign_in, sign_up
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY
from utils.queue import FakeQueue

from app.config import Settings
from app.core.hashing import hash_secret, verify_secret
from app.core.logging import JsonFormatter
from app.dependencies import get_queue
from app.main import create_app
from app.models import Account, AccountIdentity, AccountProfile

CHANGE_PATH = "/api/v1/auth/password/change"
SIGN_IN_PATH = "/api/v1/auth/sign-in"
REFRESH_PATH = "/api/v1/auth/refresh"
ACCOUNT_PATH = "/api/v1/account"
OTP_REQUEST_PATH = "/api/v1/auth/otp/request"
OTP_VERIFY_PATH = "/api/v1/auth/otp/verify"
PHRASE = "correct-horse-battery"
NEW_PHRASE = "another-correct-horse"
# Values of the shape the identity columns hold; only their being cleared matters.
STORED_RESET_HASH = "stored-reset-hash"
INVALID_CREDENTIALS = {
    "error": {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid credentials",
        "details": [],
    }
}
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


def change_body(current: str = PHRASE, new: str = NEW_PHRASE) -> dict[str, str]:
    return {"currentPassword": current, "newPassword": new}


async def identity_row(engine: AsyncEngine, email: str) -> Any:
    async with engine.connect() as connection:
        return (
            await connection.execute(
                select(
                    AccountIdentity.hash,
                    AccountIdentity.salt,
                    AccountIdentity.refresh_token.label("refresh_token"),
                    AccountIdentity.reset_token_hash.label("reset_token_hash"),
                    AccountIdentity.reset_token_expires_at.label(
                        "reset_token_expires_at"
                    ),
                    AccountIdentity.otp_hash.label("otp_hash"),
                )
                .join(
                    AccountProfile,
                    AccountProfile.account_id == AccountIdentity.account_id,
                )
                .where(AccountProfile.email == email)
            )
        ).one()


async def test_change_answers_204_stores_the_new_hash_and_clears_the_credentials_of_the_old_one(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)
        async with db_engine.begin() as connection:
            await connection.execute(
                update(AccountIdentity)
                .where(
                    AccountIdentity.account_id.in_(
                        select(AccountProfile.account_id).where(
                            AccountProfile.email == email
                        )
                    )
                )
                .values(reset_token_hash=STORED_RESET_HASH, otp_hash="stored-otp-hash")
            )

        response = await client.post(
            CHANGE_PATH, headers=tokens.headers, json=change_body()
        )

    row = await identity_row(db_engine, email)
    assert (response.status_code, response.content) == (204, b"")
    assert (
        await verify_secret(NEW_PHRASE, row.hash),
        await verify_secret(PHRASE, row.hash),
        row.salt,
    ) == (True, False, None)
    assert (
        row.refresh_token,
        row.reset_token_hash,
        row.reset_token_expires_at,
        row.otp_hash,
    ) == (None, None, None, None)


async def test_after_a_change_the_old_password_fails_the_new_one_signs_in_and_the_old_refresh_token_is_rejected(
    module_database_url: str,
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)
        await client.post(CHANGE_PATH, headers=tokens.headers, json=change_body())

        old = await client.post(SIGN_IN_PATH, json={"email": email, "password": PHRASE})
        new = await client.post(
            SIGN_IN_PATH, json={"email": email, "password": NEW_PHRASE}
        )
        refresh = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)

    assert (old.status_code, old.json(), new.status_code) == (
        401,
        INVALID_CREDENTIALS,
        200,
    )
    assert (refresh.status_code, refresh.json()) == (401, UNAUTHORIZED)


async def test_the_access_token_used_for_the_change_still_opens_the_account(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        await client.post(CHANGE_PATH, headers=tokens.headers, json=change_body())

        account = await client.get(ACCOUNT_PATH, headers=tokens.headers)

    assert account.status_code == 200


async def test_a_wrong_current_password_is_invalid_credentials_and_changes_nothing(
    module_database_url: str,
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)

        response = await client.post(
            CHANGE_PATH,
            headers=tokens.headers,
            json=change_body(current="not-the-phrase"),
        )
        # The refresh first: a successful sign-in replaces the stored refresh hash, so it would make this token stale for an unrelated reason.
        still_refreshes = await client.post(
            REFRESH_PATH, headers=tokens.refresh_headers
        )
        still_signs_in = await client.post(
            SIGN_IN_PATH, json={"email": email, "password": PHRASE}
        )

    assert (response.status_code, response.json()) == (401, INVALID_CREDENTIALS)
    assert (still_signs_in.status_code, still_refreshes.status_code) == (200, 200)


async def test_an_account_with_no_password_cannot_change_one(
    module_database_url: str,
) -> None:
    phone = "+12125550176"
    async with running_client(make_app(module_database_url)) as client:
        requested = await client.post(OTP_REQUEST_PATH, json={"phoneNumber": phone})
        signed_in = await client.post(
            OTP_VERIFY_PATH,
            json={"phoneNumber": phone, "code": requested.json()["code"]},
        )

        response = await client.post(
            CHANGE_PATH,
            headers=bearer(signed_in.json()["accessToken"]),
            json=change_body(),
        )

    assert (response.status_code, response.json()) == (401, INVALID_CREDENTIALS)


async def test_a_soft_deleted_account_cannot_change_its_password(
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

        response = await client.post(
            CHANGE_PATH, headers=tokens.headers, json=change_body()
        )

    assert (response.status_code, response.json()) == (401, INVALID_CREDENTIALS)


async def test_a_sign_in_code_requested_before_the_change_no_longer_verifies(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    phone = "+12125550177"
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)
        async with db_engine.begin() as connection:
            await connection.execute(
                update(AccountProfile)
                .where(AccountProfile.email == email)
                .values(phone_number=phone)
            )
        requested = await client.post(OTP_REQUEST_PATH, json={"phoneNumber": phone})
        await client.post(CHANGE_PATH, headers=tokens.headers, json=change_body())

        response = await client.post(
            OTP_VERIFY_PATH,
            json={"phoneNumber": phone, "code": requested.json()["code"]},
        )

    assert (response.status_code, response.json()) == (401, INVALID_CREDENTIALS)


@pytest.mark.parametrize(
    "case", ["missing", "garbage", "refresh-token", "expired-access-token"]
)
async def test_a_bad_bearer_token_is_401_unauthorized_even_with_an_invalid_body(
    module_database_url: str, frozen_clock: TimeMachineFixture, case: str
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        headers: dict[str, dict[str, str]] = {
            "missing": {},
            "garbage": bearer("garbage"),
            "refresh-token": bearer(tokens.refresh_token),
            "expired-access-token": tokens.headers,
        }
        if case == "expired-access-token":
            frozen_clock.shift(timedelta(minutes=16))

        response = await client.post(
            CHANGE_PATH,
            headers=headers[case],
            json={"currentPassword": "", "newPassword": "x"},
        )

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"currentPassword": PHRASE, "newPassword": "short"}, "newPassword"),
        ({"currentPassword": PHRASE, "newPassword": "x" * 73}, "newPassword"),
        ({"currentPassword": PHRASE, "newPassword": "ab\x00cdefgh"}, "newPassword"),
        ({"currentPassword": "", "newPassword": NEW_PHRASE}, "currentPassword"),
        ({"currentPassword": PHRASE, "newPassword": NEW_PHRASE, "role": "x"}, "role"),
    ],
    ids=[
        "new-under-8-bytes",
        "new-over-72-bytes",
        "control-character",
        "empty-current",
        "unknown-key",
    ],
)
async def test_a_bad_body_is_422_naming_the_field(
    module_database_url: str, body: dict[str, str], field: str
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)

        response = await client.post(CHANGE_PATH, headers=tokens.headers, json=body)

    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (422, "VALIDATION_FAILED")
    assert field in str(error["details"])
    assert PHRASE not in response.text


async def test_change_logs_no_password_hash_or_token(
    module_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)
        caplog.set_level(logging.DEBUG)
        await client.post(
            CHANGE_PATH, headers=tokens.headers, json=change_body(current="wrong-one-1")
        )
        await client.post(CHANGE_PATH, headers=tokens.headers, json=change_body())
        await client.post(
            CHANGE_PATH,
            headers=tokens.headers,
            json={"currentPassword": PHRASE, "newPassword": "short"},
        )

    formatter = JsonFormatter()
    output = "\n".join(formatter.format(record) for record in caplog.records)
    leaked = [
        secret
        for secret in (
            PHRASE,
            NEW_PHRASE,
            "wrong-one-1",
            "$argon2",
            tokens.access_token,
            tokens.refresh_token,
        )
        if secret in output
    ]
    assert leaked == []


async def test_no_pooled_connection_is_held_while_either_password_step_runs(
    module_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A caller with a valid token must not be able to fill the pool through the two Argon2 steps (verify the current, hash the new).
    app = make_app(module_database_url)
    steps: list[tuple[str, int]] = []

    async def watching_verify_secret(secret: str, hashed: str) -> bool:
        steps.append(("verify", app.state.engine.pool.checkedout()))
        return await verify_secret(secret, hashed)

    async def watching_hash_secret(secret: str) -> str:
        steps.append(("hash", app.state.engine.pool.checkedout()))
        return await hash_secret(secret)

    async with running_client(app) as client:
        tokens = await sign_up(client, unique_email(), PHRASE)
        monkeypatch.setattr(
            "app.services.password_auth.verify_secret", watching_verify_secret
        )
        monkeypatch.setattr(
            "app.services.password_auth.hash_secret", watching_hash_secret
        )

        await client.post(CHANGE_PATH, headers=tokens.headers, json=change_body())

    assert steps == [("verify", 0), ("hash", 0)]


async def test_the_helper_can_sign_in_with_the_new_password(
    module_database_url: str,
) -> None:
    email = unique_email()
    async with running_client(make_app(module_database_url)) as client:
        tokens = await sign_up(client, email, PHRASE)
        await client.post(CHANGE_PATH, headers=tokens.headers, json=change_body())

        again = await sign_in(client, email, NEW_PHRASE)

    assert again.access_token != tokens.access_token
