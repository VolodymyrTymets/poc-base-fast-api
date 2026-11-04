"""POST /api/v1/auth/otp/verify over HTTP on a real database. Task: 7.2 (ports `sign-in-otp.e2e-spec.ts`).

The request has its own session, so rows are read through `db_engine`; they stay for the module, so each test uses a phone of its own.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from time_machine import TimeMachineFixture
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY
from utils.queue import FakeQueue

from app.config import Settings
from app.core.hashing import verify_secret
from app.core.security import TokenType, verify_token
from app.dependencies import get_queue
from app.main import create_app
from app.models import AccountIdentity, AccountProfile
from app.services.otp import OTP_TTL

REQUEST_PATH = "/api/v1/auth/otp/request"
VERIFY_PATH = "/api/v1/auth/otp/verify"
ACCOUNT_PATH = "/api/v1/account"
INVALID_CREDENTIALS = {
    "error": {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid credentials",
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


async def request_code(client: httpx.AsyncClient, phone: str) -> str:
    response = await client.post(REQUEST_PATH, json={"phoneNumber": phone})
    assert response.status_code == 200
    code: str = response.json()["code"]
    return code


@dataclass(frozen=True)
class Stored:
    otp_hash: str | None
    otp_salt: str | None
    otp_expires_at: datetime | None
    refresh_token: str | None
    is_phone_verified: bool


async def stored(engine: AsyncEngine, phone: str) -> Stored:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                select(
                    AccountIdentity.otp_hash,
                    AccountIdentity.otp_salt,
                    AccountIdentity.otp_expires_at,
                    AccountIdentity.refresh_token,
                    AccountProfile.is_phone_verified,
                )
                .join(
                    AccountProfile,
                    AccountProfile.account_id == AccountIdentity.account_id,
                )
                .where(AccountProfile.phone_number == phone)
            )
        ).one()
    return Stored(*row)


async def test_a_valid_code_signs_in_and_the_access_token_opens_the_account(
    module_database_url: str, db_engine: AsyncEngine, frozen_clock: TimeMachineFixture
) -> None:
    phone = "+12125550171"
    async with running_client(make_app(module_database_url)) as client:
        code = await request_code(client, phone)

        response = await client.post(
            VERIFY_PATH, json={"phoneNumber": phone, "code": code}
        )
        body = response.json()
        account = await client.get(
            ACCOUNT_PATH,
            headers={"Authorization": f"Bearer {body['accessToken']}"},
        )

    settings = Settings(
        app_env="test", jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY
    )
    access = verify_token(settings, body["accessToken"], TokenType.ACCESS)
    refresh = verify_token(settings, body["refreshToken"], TokenType.REFRESH)
    assert (
        response.status_code,
        sorted(body),
        access.account_id == refresh.account_id,
        account.status_code,
        account.json()["id"] == access.account_id,
        account.json()["profile"]["phoneNumber"],
    ) == (200, ["accessToken", "refreshToken"], True, 200, True, phone)


async def test_success_clears_the_code_verifies_the_phone_and_stores_the_refresh_sha256(
    module_database_url: str, db_engine: AsyncEngine, frozen_clock: TimeMachineFixture
) -> None:
    phone = "+12125550172"
    async with running_client(make_app(module_database_url)) as client:
        code = await request_code(client, phone)
        response = await client.post(
            VERIFY_PATH, json={"phoneNumber": phone, "code": code}
        )

    row = await stored(db_engine, phone)
    refresh = response.json()["refreshToken"]
    assert (
        row.otp_hash,
        row.otp_salt,
        row.otp_expires_at,
        row.is_phone_verified,
        row.refresh_token,
    ) == (
        None,
        None,
        None,
        True,
        hashlib.sha256(refresh.encode()).hexdigest(),
    )


async def test_a_wrong_code_is_invalid_credentials_and_changes_nothing(
    module_database_url: str, db_engine: AsyncEngine, frozen_clock: TimeMachineFixture
) -> None:
    phone = "+12125550173"
    async with running_client(make_app(module_database_url)) as client:
        await request_code(client, phone)
        response = await client.post(
            VERIFY_PATH, json={"phoneNumber": phone, "code": "000000"}
        )

    row = await stored(db_engine, phone)
    assert (
        response.status_code,
        response.json(),
        row.otp_hash is not None,
        row.refresh_token,
        row.is_phone_verified,
    ) == (401, INVALID_CREDENTIALS, True, None, False)


async def test_an_unknown_phone_gets_the_same_401_body(
    module_database_url: str, frozen_clock: TimeMachineFixture
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        response = await client.post(
            VERIFY_PATH, json={"phoneNumber": "+12125550179", "code": "123456"}
        )

    assert (response.status_code, response.json()) == (401, INVALID_CREDENTIALS)


async def test_an_expired_code_gets_the_same_401_body(
    module_database_url: str, frozen_clock: TimeMachineFixture
) -> None:
    phone = "+12125550174"
    async with running_client(make_app(module_database_url)) as client:
        code = await request_code(client, phone)
        frozen_clock.shift(OTP_TTL + timedelta(seconds=1))
        response = await client.post(
            VERIFY_PATH, json={"phoneNumber": phone, "code": code}
        )

    assert (response.status_code, response.json()) == (401, INVALID_CREDENTIALS)


async def test_a_code_cannot_be_used_twice(
    module_database_url: str, frozen_clock: TimeMachineFixture
) -> None:
    phone = "+12125550175"
    async with running_client(make_app(module_database_url)) as client:
        code = await request_code(client, phone)
        first = await client.post(
            VERIFY_PATH, json={"phoneNumber": phone, "code": code}
        )
        second = await client.post(
            VERIFY_PATH, json={"phoneNumber": phone, "code": code}
        )

    assert (first.status_code, second.status_code, second.json()) == (
        200,
        401,
        INVALID_CREDENTIALS,
    )


async def test_two_sign_ins_rotate_the_refresh_token(
    module_database_url: str, db_engine: AsyncEngine, frozen_clock: TimeMachineFixture
) -> None:
    phone = "+12125550176"
    async with running_client(make_app(module_database_url)) as client:
        first_code = await request_code(client, phone)
        first = await client.post(
            VERIFY_PATH, json={"phoneNumber": phone, "code": first_code}
        )
        second_code = await request_code(client, phone)
        second = await client.post(
            VERIFY_PATH, json={"phoneNumber": phone, "code": second_code}
        )

    row = await stored(db_engine, phone)
    first_refresh = first.json()["refreshToken"]
    second_refresh = second.json()["refreshToken"]
    assert (
        first_refresh != second_refresh,
        row.refresh_token,
    ) == (True, hashlib.sha256(second_refresh.encode()).hexdigest())


@pytest.mark.parametrize(
    "payload",
    [
        {"phoneNumber": "not a phone", "code": "123456"},
        {"code": "123456"},
        {"phoneNumber": "+12125550177"},
        {"phoneNumber": "+12125550177", "code": "1234567"},
        {"phoneNumber": "+12125550177", "code": "123456", "extra": 1},
    ],
    ids=["bad-phone", "no-phone", "no-code", "long-code", "extra-key"],
)
async def test_a_malformed_body_is_a_validation_error(
    module_database_url: str, payload: dict[str, object]
) -> None:
    async with running_client(make_app(module_database_url)) as client:
        response = await client.post(VERIFY_PATH, json=payload)

    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "VALIDATION_FAILED",
    )


async def test_an_expired_access_token_is_unauthorized_on_a_guarded_route(
    module_database_url: str, frozen_clock: TimeMachineFixture
) -> None:
    phone = "+12125550178"
    async with running_client(make_app(module_database_url)) as client:
        code = await request_code(client, phone)
        tokens = (
            await client.post(VERIFY_PATH, json={"phoneNumber": phone, "code": code})
        ).json()
        frozen_clock.shift(timedelta(minutes=16))
        response = await client.get(
            ACCOUNT_PATH, headers={"Authorization": f"Bearer {tokens['accessToken']}"}
        )

    assert (response.status_code, response.json()["error"]["code"]) == (
        401,
        "UNAUTHORIZED",
    )


@pytest.mark.parametrize(
    ("phone", "send_right_code"),
    [("+12125550180", True), ("+12125550181", False), ("+12125550189", False)],
    ids=["right-code", "wrong-code", "unknown-phone"],
)
async def test_no_pooled_connection_is_held_while_the_code_is_hashed(
    module_database_url: str,
    frozen_clock: TimeMachineFixture,
    monkeypatch: pytest.MonkeyPatch,
    phone: str,
    send_right_code: bool,
) -> None:
    # The endpoint is unauthenticated: a connection held through the Argon2 check would let a flood of calls fill the pool (POC-7.2 review).
    app = make_app(module_database_url)
    checked_out_during_hash: list[int] = []

    async def watching_verify_secret(secret: str, hashed: str) -> bool:
        checked_out_during_hash.append(app.state.engine.pool.checkedout())
        return await verify_secret(secret, hashed)

    async with running_client(app) as client:
        if phone != "+12125550189":
            code = await request_code(client, phone)
        else:
            code = "123456"
        monkeypatch.setattr("app.services.otp.verify_secret", watching_verify_secret)

        await client.post(
            VERIFY_PATH,
            json={"phoneNumber": phone, "code": code if send_right_code else "000000"},
        )

    assert checked_out_during_hash == [0]
