"""The auth helper of task 3.2, proved against stub routes.

The real endpoints do not exist yet (JWT is task 4.4, sign-up and sign-in are 7.3), so the app gets test-only routes that
follow the ENDPOINTS.md contract. That proves the plumbing of the helper (body sent, status checked, tokens parsed, headers
accepted), not that the real endpoints answer this way: the e2e tests of 7.3 are its first real run.
"""

from typing import Annotated

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from utils.auth import AuthTokens, sign_in, sign_up

from app.core.errors import InvalidCredentialsError

STUB_ACCESS = "stub-access-token"
STUB_REFRESH = "stub-refresh-token"
VALID_PHRASE = "correct-horse-battery"
INVALID_PHRASE = "not-the-phrase"
MALFORMED_EMAIL = "malformed@example.test"


class Credentials(BaseModel):
    # extra="forbid": the helper must send exactly {email, password}, as the contract says.
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


@pytest.fixture
def stub_auth_routes(asgi_app: FastAPI) -> None:
    @asgi_app.post("/api/v1/auth/sign-up", status_code=201)
    async def sign_up_stub(body: Credentials) -> dict[str, str]:
        if body.email == MALFORMED_EMAIL:
            return {"accessToken": STUB_ACCESS}
        return {"accessToken": STUB_ACCESS, "refreshToken": STUB_REFRESH}

    @asgi_app.post("/api/v1/auth/sign-in", status_code=200)
    async def sign_in_stub(body: Credentials) -> dict[str, str]:
        if body.password != VALID_PHRASE:
            # The domain error, as the real sign-in raises it: since task 4.2 an HTTPException 401 is always
            # UNAUTHORIZED and its `detail` is dropped (issue I.10).
            raise InvalidCredentialsError
        return {"accessToken": STUB_ACCESS, "refreshToken": STUB_REFRESH}

    @asgi_app.get("/api/v1/_whoami")
    async def whoami(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        if authorization != f"Bearer {STUB_ACCESS}":
            raise HTTPException(status_code=401, detail="UNAUTHORIZED")
        return {"who": "stub"}

    @asgi_app.get("/api/v1/_refreshing")
    async def refreshing(
        x_refresh_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        if x_refresh_token != STUB_REFRESH:
            raise HTTPException(status_code=401, detail="UNAUTHORIZED")
        return {"refreshing": "yes"}


@pytest.mark.usefixtures("stub_auth_routes")
async def test_sign_up_gives_headers_the_guarded_route_accepts(
    client: httpx.AsyncClient,
) -> None:
    tokens = await sign_up(client, "new@example.test", VALID_PHRASE)

    guarded = await client.get("/api/v1/_whoami", headers=tokens.headers)
    bare = await client.get("/api/v1/_whoami")

    assert (guarded.status_code, guarded.json(), bare.status_code) == (
        200,
        {"who": "stub"},
        401,
    )


@pytest.mark.usefixtures("stub_auth_routes")
async def test_sign_in_gives_access_and_refresh_headers(
    client: httpx.AsyncClient,
) -> None:
    tokens = await sign_in(client, "existing@example.test", VALID_PHRASE)

    refreshing = await client.get("/api/v1/_refreshing", headers=tokens.refresh_headers)
    access_only = await client.get("/api/v1/_refreshing", headers=tokens.headers)

    assert tokens == AuthTokens(STUB_ACCESS, STUB_REFRESH)
    assert (refreshing.status_code, access_only.status_code) == (200, 401)


@pytest.mark.usefixtures("stub_auth_routes")
async def test_an_unexpected_status_fails_with_the_status_and_the_body(
    client: httpx.AsyncClient,
) -> None:
    with pytest.raises(
        AssertionError, match=r"sign-in answered 401, expected 200.*INVALID_CREDENTIALS"
    ):
        await sign_in(client, "existing@example.test", INVALID_PHRASE)


@pytest.mark.usefixtures("stub_auth_routes")
async def test_a_body_without_both_tokens_fails_naming_what_came_back(
    client: httpx.AsyncClient,
) -> None:
    with pytest.raises(ValidationError, match="refreshToken"):
        await sign_up(client, MALFORMED_EMAIL, VALID_PHRASE)
