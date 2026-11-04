import logging
import uuid
from datetime import timedelta
from typing import Annotated, Any

import jwt
import pytest
from fastapi import Depends, FastAPI
from utils.client import running_client
from utils.clock import FROZEN_NOW
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.security import TokenClaims, TokenType, issue_token
from app.dependencies import (
    RefreshCredentials,
    current_account,
    refresh_account,
    refresh_credentials,
)
from app.main import create_app

ACCOUNT_ID = str(uuid.UUID("22222222-2222-4222-8222-222222222222"))
# database_url=None: this is built at import, before the autouse fixture isolates the environment, so it would read a
# developer's .env, and the lifespan would then seed that database (task 5.1). These tests need none.
SETTINGS = Settings(
    jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY, database_url=None
)
UNAUTHORIZED = {
    "error": {
        "code": "UNAUTHORIZED",
        "message": "Authentication required",
        "details": [],
    }
}


def make_app(settings: Settings = SETTINGS) -> FastAPI:
    app = create_app(settings)

    # No route uses the dependencies yet, so the test adds its own to this instance.
    @app.get("/api/v1/_me")
    async def me(
        claims: Annotated[TokenClaims, Depends(current_account)],
    ) -> dict[str, str]:
        return {"id": claims.account_id, "jti": claims.jti}

    @app.post("/api/v1/_refresh")
    async def refresh(
        claims: Annotated[TokenClaims, Depends(refresh_account)],
    ) -> dict[str, str]:
        return {"id": claims.account_id, "jti": claims.jti}

    @app.post("/api/v1/_refresh_credentials")
    async def refresh_with_token(
        credentials: Annotated[RefreshCredentials, Depends(refresh_credentials)],
    ) -> dict[str, str]:
        return {"id": credentials.account_id, "token": credentials.token}

    return app


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def access_token() -> str:
    return issue_token(SETTINGS, ACCOUNT_ID, TokenType.ACCESS)


def refresh_token() -> str:
    return issue_token(SETTINGS, ACCOUNT_ID, TokenType.REFRESH)


def tampered(token: str) -> str:
    head, body, signature = token.split(".")
    return f"{head}.{body}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"


async def test_a_valid_access_token_reaches_the_handler(frozen_clock: Any) -> None:
    async with running_client(make_app()) as client:
        response = await client.get("/api/v1/_me", headers=bearer(access_token()))

    assert response.status_code == 200
    assert response.json()["id"] == ACCOUNT_ID
    assert response.json()["jti"]


async def test_the_scheme_name_is_case_insensitive(frozen_clock: Any) -> None:
    async with running_client(make_app()) as client:
        response = await client.get(
            "/api/v1/_me", headers={"Authorization": f"bearer {access_token()}"}
        )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer not-a-token"},
    ],
    ids=["no-header", "empty-token", "no-token", "other-scheme", "garbage"],
)
async def test_a_missing_or_malformed_bearer_is_unauthorized(
    headers: dict[str, str],
) -> None:
    async with running_client(make_app()) as client:
        response = await client.get("/api/v1/_me", headers=headers)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_an_expired_access_token_is_unauthorized(frozen_clock: Any) -> None:
    token = access_token()
    frozen_clock.shift(timedelta(minutes=15))

    async with running_client(make_app()) as client:
        response = await client.get("/api/v1/_me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


async def test_a_tampered_access_token_is_unauthorized(frozen_clock: Any) -> None:
    async with running_client(make_app()) as client:
        response = await client.get(
            "/api/v1/_me", headers=bearer(tampered(access_token()))
        )

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


async def test_a_refresh_token_is_not_an_access_token(frozen_clock: Any) -> None:
    async with running_client(make_app()) as client:
        response = await client.get("/api/v1/_me", headers=bearer(refresh_token()))

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


async def test_a_valid_refresh_token_reaches_the_handler(frozen_clock: Any) -> None:
    async with running_client(make_app()) as client:
        response = await client.post(
            "/api/v1/_refresh", headers={"x-refresh-token": refresh_token()}
        )

    assert response.status_code == 200
    assert response.json()["id"] == ACCOUNT_ID


@pytest.mark.parametrize(
    "headers", [{}, {"x-refresh-token": ""}, {"x-refresh-token": "garbage"}]
)
async def test_a_missing_or_malformed_refresh_token_is_unauthorized(
    headers: dict[str, str],
) -> None:
    async with running_client(make_app()) as client:
        response = await client.post("/api/v1/_refresh", headers=headers)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert "www-authenticate" not in response.headers


async def test_refresh_account_rejects_expired_tampered_and_access_tokens(
    frozen_clock: Any,
) -> None:
    token = refresh_token()
    async with running_client(make_app()) as client:
        tampered_response = await client.post(
            "/api/v1/_refresh", headers={"x-refresh-token": tampered(token)}
        )
        access_response = await client.post(
            "/api/v1/_refresh", headers={"x-refresh-token": access_token()}
        )
        # An Authorization header is not a refresh token.
        bearer_response = await client.post("/api/v1/_refresh", headers=bearer(token))
        frozen_clock.shift(timedelta(days=7))
        expired_response = await client.post(
            "/api/v1/_refresh", headers={"x-refresh-token": token}
        )

    for response in (
        tampered_response,
        access_response,
        bearer_response,
        expired_response,
    ):
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED


async def test_a_token_signed_with_the_other_secret_is_rejected(
    frozen_clock: Any,
) -> None:
    forged = jwt.encode(
        {
            "sub": ACCOUNT_ID,
            "jti": "x",
            "typ": "access",
            "iat": FROZEN_NOW,
            "exp": FROZEN_NOW + timedelta(minutes=15),
        },
        REFRESH_KEY.get_secret_value(),
        algorithm="HS256",
    )

    async with running_client(make_app()) as client:
        response = await client.get("/api/v1/_me", headers=bearer(forged))

    assert response.status_code == 401


async def test_no_token_reaches_the_logs_or_the_body(
    frozen_clock: Any, caplog: pytest.LogCaptureFixture
) -> None:
    token = tampered(access_token())

    with caplog.at_level(logging.DEBUG):
        async with running_client(make_app()) as client:
            response = await client.get("/api/v1/_me", headers=bearer(token))

    assert token not in response.text
    assert token not in caplog.text


async def test_an_unset_secret_is_a_server_error_not_a_pass() -> None:
    app = make_app(Settings(jwt_secret=None, jwt_refresh_token_secret=None))

    async with running_client(app, raise_app_exceptions=False) as client:
        response = await client.get("/api/v1/_me", headers=bearer("a.b.c"))

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"


async def test_refresh_credentials_carry_the_account_and_the_raw_header_token(
    frozen_clock: Any,
) -> None:
    token = refresh_token()
    async with running_client(make_app()) as client:
        response = await client.post(
            "/api/v1/_refresh_credentials", headers={"x-refresh-token": token}
        )

    assert (response.status_code, response.json()) == (
        200,
        {"id": ACCOUNT_ID, "token": token},
    )


@pytest.mark.parametrize(
    "headers", [{}, {"x-refresh-token": ""}, {"x-refresh-token": "garbage"}]
)
async def test_refresh_credentials_reject_what_refresh_account_rejects(
    frozen_clock: Any, headers: dict[str, str]
) -> None:
    async with running_client(make_app()) as client:
        response = await client.post("/api/v1/_refresh_credentials", headers=headers)

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)


async def test_refresh_credentials_reject_an_access_token(frozen_clock: Any) -> None:
    async with running_client(make_app()) as client:
        response = await client.post(
            "/api/v1/_refresh_credentials", headers={"x-refresh-token": access_token()}
        )

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)
