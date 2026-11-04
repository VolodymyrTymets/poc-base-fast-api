"""POST /api/v1/auth/password/restore and /reset over HTTP on a real database. Task: 7.6 (ports `restore-password.e2e-spec.ts`).

The request has its own session, so rows are read and changed through `db_engine`; they stay for the module, so each test uses an address or phone of its own.
The token reaches the test the way it reaches the worker: as an argument of the `send_password_reset` job on the `FakeQueue`.
"""

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
from utils.auth import sign_up
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY
from utils.queue import FakeQueue

from app.config import Settings
from app.core.hashing import hash_secret, verify_secret
from app.core.logging import JsonFormatter
from app.dependencies import get_queue
from app.main import create_app
from app.models import Account, AccountIdentity, AccountProfile

RESTORE_PATH = "/api/v1/auth/password/restore"
RESET_PATH = "/api/v1/auth/password/reset"
SIGN_IN_PATH = "/api/v1/auth/sign-in"
REFRESH_PATH = "/api/v1/auth/refresh"
OTP_REQUEST_PATH = "/api/v1/auth/otp/request"
PHRASE = "correct-horse-battery"
NEW_PHRASE = "another-correct-horse"
SUCCESS = {"success": True}
INVALID_RESET_TOKEN = {
    "error": {
        "code": "INVALID_RESET_TOKEN",
        "message": "Invalid or expired reset token",
        "details": [],
    }
}
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


def make_app(database_url: str, queue: FakeQueue) -> FastAPI:
    app = create_app(
        Settings(
            app_env="test",
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )
    app.dependency_overrides[get_queue] = lambda: queue
    return app


def unique_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


def latest_token(queue: FakeQueue) -> str:
    """The token of the newest `send_password_reset` job, as the worker would receive it (account id, email, token)."""
    token = queue.named("send_password_reset")[-1].args[2]
    assert isinstance(token, str)
    return token


async def reset_columns(engine: AsyncEngine, email: str) -> Any:
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


async def test_restore_then_reset_gives_the_new_password_and_ends_the_old_sessions(
    module_database_url: str,
) -> None:
    email = unique_email()
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        tokens = await sign_up(client, email, PHRASE)
        restored = await client.post(RESTORE_PATH, json={"email": email})

        reset = await client.post(
            RESET_PATH, json={"token": latest_token(queue), "newPassword": NEW_PHRASE}
        )
        old = await client.post(SIGN_IN_PATH, json={"email": email, "password": PHRASE})
        new = await client.post(
            SIGN_IN_PATH, json={"email": email, "password": NEW_PHRASE}
        )
        refresh = await client.post(REFRESH_PATH, headers=tokens.refresh_headers)

    assert (restored.status_code, restored.json()) == (200, SUCCESS)
    assert (reset.status_code, reset.content) == (204, b"")
    assert (old.status_code, old.json(), new.status_code) == (
        401,
        INVALID_CREDENTIALS,
        200,
    )
    assert (refresh.status_code, refresh.json()) == (401, UNAUTHORIZED)


async def test_restore_stores_the_sha256_of_the_token_and_queues_one_email_job(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        await sign_up(client, email, PHRASE)

        response = await client.post(RESTORE_PATH, json={"email": email})

    token = latest_token(queue)
    row = await reset_columns(db_engine, email)
    assert response.json() == SUCCESS
    assert token not in response.text
    assert len(queue.named("send_password_reset")) == 1
    assert (len(token), row.reset_token_hash) == (
        64,
        hashlib.sha256(token.encode()).hexdigest(),
    )
    assert row.reset_token_hash != token


async def test_restore_for_an_unknown_email_answers_the_same_and_sends_nothing(
    module_database_url: str,
) -> None:
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        response = await client.post(RESTORE_PATH, json={"email": unique_email()})

    assert (response.status_code, response.json(), queue.jobs) == (200, SUCCESS, [])


async def test_restore_for_a_soft_deleted_account_answers_the_same_and_sends_nothing(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        await sign_up(client, email, PHRASE)
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

        response = await client.post(RESTORE_PATH, json={"email": email})

    assert (response.status_code, response.json(), queue.jobs) == (200, SUCCESS, [])


async def test_restore_with_the_queue_down_still_answers_200(
    module_database_url: str,
) -> None:
    email = unique_email()
    queue = FakeQueue(fail_on=["send_password_reset"])
    async with running_client(make_app(module_database_url, queue)) as client:
        await sign_up(client, email, PHRASE)

        response = await client.post(RESTORE_PATH, json={"email": email})

    assert (response.status_code, response.json(), queue.jobs) == (200, SUCCESS, [])


async def test_a_second_restore_invalidates_the_first_token(
    module_database_url: str,
) -> None:
    email = unique_email()
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        await sign_up(client, email, PHRASE)
        await client.post(RESTORE_PATH, json={"email": email})
        first = latest_token(queue)
        await client.post(RESTORE_PATH, json={"email": email})
        second = latest_token(queue)

        with_first = await client.post(
            RESET_PATH, json={"token": first, "newPassword": NEW_PHRASE}
        )
        with_second = await client.post(
            RESET_PATH, json={"token": second, "newPassword": NEW_PHRASE}
        )

    assert (first != second, with_first.status_code, with_second.status_code) == (
        True,
        400,
        204,
    )


async def test_reset_clears_the_credentials_of_the_old_password(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        await sign_up(client, email, PHRASE)
        await client.post(RESTORE_PATH, json={"email": email})
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
                .values(otp_hash="stored-otp-hash")
            )

        await client.post(
            RESET_PATH, json={"token": latest_token(queue), "newPassword": NEW_PHRASE}
        )

    row = await reset_columns(db_engine, email)
    assert (
        await verify_secret(NEW_PHRASE, row.hash),
        row.salt,
        row.refresh_token,
        row.reset_token_hash,
        row.reset_token_expires_at,
        row.otp_hash,
    ) == (True, None, None, None, None, None)


async def test_an_account_made_by_otp_sets_its_first_password_with_restore_and_reset(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    email = unique_email()
    phone = "+12125550178"
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        await client.post(OTP_REQUEST_PATH, json={"phoneNumber": phone})
        async with db_engine.begin() as connection:
            await connection.execute(
                update(AccountProfile)
                .where(AccountProfile.phone_number == phone)
                .values(email=email)
            )
        await client.post(RESTORE_PATH, json={"email": email})

        reset = await client.post(
            RESET_PATH, json={"token": latest_token(queue), "newPassword": NEW_PHRASE}
        )
        signed_in = await client.post(
            SIGN_IN_PATH, json={"email": email, "password": NEW_PHRASE}
        )

    assert (reset.status_code, signed_in.status_code) == (204, 200)


async def test_a_reset_token_works_once(module_database_url: str) -> None:
    email = unique_email()
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        await sign_up(client, email, PHRASE)
        await client.post(RESTORE_PATH, json={"email": email})
        token = latest_token(queue)
        await client.post(RESET_PATH, json={"token": token, "newPassword": NEW_PHRASE})

        again = await client.post(
            RESET_PATH, json={"token": token, "newPassword": "a-third-phrase-1"}
        )
        signed_in = await client.post(
            SIGN_IN_PATH, json={"email": email, "password": NEW_PHRASE}
        )

    assert (again.status_code, again.json(), signed_in.status_code) == (
        400,
        INVALID_RESET_TOKEN,
        200,
    )


async def test_an_expired_token_is_400_and_keeps_the_current_password(
    module_database_url: str, frozen_clock: TimeMachineFixture
) -> None:
    email = unique_email()
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        await sign_up(client, email, PHRASE)
        await client.post(RESTORE_PATH, json={"email": email})
        # The token lives 30 minutes.
        frozen_clock.shift(timedelta(minutes=31))

        reset = await client.post(
            RESET_PATH, json={"token": latest_token(queue), "newPassword": NEW_PHRASE}
        )
        signed_in = await client.post(
            SIGN_IN_PATH, json={"email": email, "password": PHRASE}
        )

    assert (reset.status_code, reset.json(), signed_in.status_code) == (
        400,
        INVALID_RESET_TOKEN,
        200,
    )


async def test_a_garbage_token_is_400_invalid_reset_token(
    module_database_url: str,
) -> None:
    async with running_client(make_app(module_database_url, FakeQueue())) as client:
        response = await client.post(
            RESET_PATH, json={"token": "garbage", "newPassword": NEW_PHRASE}
        )

    assert (response.status_code, response.json()) == (400, INVALID_RESET_TOKEN)


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        (RESTORE_PATH, {"email": "not-an-email"}, "email"),
        (RESTORE_PATH, {"email": "a@example.com", "role": "x"}, "role"),
        (RESET_PATH, {"token": "", "newPassword": NEW_PHRASE}, "token"),
        (RESET_PATH, {"token": "t" * 201, "newPassword": NEW_PHRASE}, "token"),
        (RESET_PATH, {"token": "t", "newPassword": "short"}, "newPassword"),
        (RESET_PATH, {"token": "t", "newPassword": "x" * 73}, "newPassword"),
        (RESET_PATH, {"token": "t", "newPassword": "ab\x00cdefgh"}, "newPassword"),
        (RESET_PATH, {"token": "t", "newPassword": NEW_PHRASE, "role": "x"}, "role"),
    ],
    ids=[
        "restore-bad-email",
        "restore-unknown-key",
        "reset-empty-token",
        "reset-token-over-200",
        "reset-short-password",
        "reset-password-over-72-bytes",
        "reset-control-character",
        "reset-unknown-key",
    ],
)
async def test_a_bad_body_is_422_naming_the_field(
    module_database_url: str, path: str, body: dict[str, str], field: str
) -> None:
    async with running_client(make_app(module_database_url, FakeQueue())) as client:
        response = await client.post(path, json=body)

    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (422, "VALIDATION_FAILED")
    assert field in str(error["details"])
    assert NEW_PHRASE not in response.text


async def test_restore_and_reset_log_no_token_password_or_hash(
    module_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    email = unique_email()
    queue = FakeQueue()
    async with running_client(make_app(module_database_url, queue)) as client:
        await sign_up(client, email, PHRASE)
        caplog.set_level(logging.DEBUG)
        await client.post(RESTORE_PATH, json={"email": email})
        token = latest_token(queue)
        await client.post(RESET_PATH, json={"token": token, "newPassword": NEW_PHRASE})
        await client.post(
            RESET_PATH, json={"token": token, "newPassword": "a-third-phrase-1"}
        )

    formatter = JsonFormatter()
    output = "\n".join(formatter.format(record) for record in caplog.records)
    secrets_seen = (token, NEW_PHRASE, "a-third-phrase-1", PHRASE, "$argon2")
    assert tuple(secret in output for secret in secrets_seen) == (False,) * 5


async def test_no_pooled_connection_is_held_while_the_new_password_is_hashed(
    module_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The route is unauthenticated: a connection held through the Argon2 hash would let a flood of calls fill the pool.
    email = unique_email()
    queue = FakeQueue()
    app = make_app(module_database_url, queue)
    checked_out_during_hash: list[int] = []

    async def watching_hash_secret(secret: str) -> str:
        checked_out_during_hash.append(app.state.engine.pool.checkedout())
        return await hash_secret(secret)

    async with running_client(app) as client:
        await sign_up(client, email, PHRASE)
        await client.post(RESTORE_PATH, json={"email": email})
        monkeypatch.setattr(
            "app.services.password_auth.hash_secret", watching_hash_secret
        )

        await client.post(
            RESET_PATH, json={"token": latest_token(queue), "newPassword": NEW_PHRASE}
        )

    assert checked_out_during_hash == [0]
