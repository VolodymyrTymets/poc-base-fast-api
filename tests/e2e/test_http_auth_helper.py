"""The auth helper of task 3.2, proved against the real sign-up and sign-in routes of task 7.3.

Until 7.3 the helper was proved against stub routes written to the ENDPOINTS.md contract. The real routes replace them, so the helper's
plumbing (body sent, status checked, tokens parsed, headers accepted) is now shown end to end. Two stubs remain, each for something
no real route offers yet: `_refreshing` (`POST /auth/refresh` is task 7.4) and a sign-up that answers without a refresh token (the real
one never does).
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from pydantic import ValidationError
from utils.auth import AuthTokens, sign_in, sign_up
from utils.client import client_for, running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.errors import UnauthorizedError
from app.core.security import TokenType, verify_token
from app.main import create_app

VALID_PHRASE = "correct-horse-battery"
INVALID_PHRASE = "not-the-phrase"


def new_email() -> str:
    # Commits persist for the module, so every test registers an address of its own.
    return f"{uuid.uuid4().hex}@example.com"


@pytest.fixture
def auth_settings(module_database_url: str) -> Settings:
    # The default `asgi_app` has no token secrets, so it cannot issue a token; the real routes need them.
    return Settings(
        app_env="test",
        database_url=module_database_url,
        jwt_secret=ACCESS_KEY,
        jwt_refresh_token_secret=REFRESH_KEY,
    )


@pytest.fixture
async def auth_client(auth_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(auth_settings)

    @app.get("/api/v1/_refreshing")
    async def refreshing(
        x_refresh_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        # Stands in for `POST /auth/refresh` (task 7.4): accepts only a valid refresh token.
        try:
            verify_token(auth_settings, x_refresh_token or "", TokenType.REFRESH)
        except UnauthorizedError as error:
            raise HTTPException(status_code=401, detail="UNAUTHORIZED") from error
        return {"refreshing": "yes"}

    async with running_client(app) as client:
        yield client


async def test_sign_up_gives_headers_the_guarded_route_accepts(
    auth_client: httpx.AsyncClient,
) -> None:
    email = new_email()

    tokens = await sign_up(auth_client, email, VALID_PHRASE)

    guarded = await auth_client.get("/api/v1/account", headers=tokens.headers)
    bare = await auth_client.get("/api/v1/account")
    # WHY: the real route answers the signed-in account, not the stub's fixed body (POC-7.3).
    assert (
        guarded.status_code,
        guarded.json()["profile"]["email"],
        bare.status_code,
    ) == (
        200,
        email,
        401,
    )


async def test_sign_in_gives_access_and_refresh_headers(
    auth_client: httpx.AsyncClient, auth_settings: Settings
) -> None:
    email = new_email()
    await sign_up(auth_client, email, VALID_PHRASE)

    tokens = await sign_in(auth_client, email, VALID_PHRASE)

    refreshing = await auth_client.get(
        "/api/v1/_refreshing", headers=tokens.refresh_headers
    )
    access_only = await auth_client.get("/api/v1/_refreshing", headers=tokens.headers)
    # WHY: real routes issue non-deterministic JWTs, so equality with fixed stub tokens becomes "each token passes its own check" (POC-7.3).
    access = verify_token(auth_settings, tokens.access_token, TokenType.ACCESS)
    refresh = verify_token(auth_settings, tokens.refresh_token, TokenType.REFRESH)
    assert access.account_id == refresh.account_id
    assert (refreshing.status_code, access_only.status_code) == (200, 401)


async def test_an_unexpected_status_fails_with_the_status_and_the_body(
    auth_client: httpx.AsyncClient,
) -> None:
    email = new_email()
    await sign_up(auth_client, email, VALID_PHRASE)

    with pytest.raises(
        AssertionError, match=r"sign-in answered 401, expected 200.*INVALID_CREDENTIALS"
    ):
        await sign_in(auth_client, email, INVALID_PHRASE)


async def test_a_body_without_both_tokens_fails_naming_what_came_back() -> None:
    # A bare app of its own: the real sign-up route would shadow a stub added to the real app. The real route never answers without both tokens.
    app = FastAPI()

    @app.post("/api/v1/auth/sign-up", status_code=201)
    async def sign_up_without_a_refresh_token() -> dict[str, str]:
        return {"accessToken": "only-the-access-token"}

    async with client_for(app) as client:
        with pytest.raises(ValidationError, match="refreshToken"):
            await sign_up(client, new_email(), VALID_PHRASE)


def test_auth_tokens_expose_the_two_header_shapes() -> None:
    tokens = AuthTokens("access", "refresh")

    assert (tokens.headers, tokens.refresh_headers) == (
        {"Authorization": "Bearer access"},
        {"x-refresh-token": "refresh"},
    )
