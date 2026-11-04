"""Sign up and sign in over HTTP and get the headers the guarded routes expect.

Written to the contract in docs/api/ENDPOINTS.md (rows `signUp` and `signIn`, built in task 7.3): `POST /api/v1/auth/sign-up` answers 201 and
`POST /api/v1/auth/sign-in` answers 200, both with `{accessToken, refreshToken}`; a guarded route reads
`Authorization: Bearer <accessToken>`, and `POST /auth/refresh` reads `x-refresh-token` (ADR-0008).
"""

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field

SIGN_UP_PATH = "/api/v1/auth/sign-up"
SIGN_IN_PATH = "/api/v1/auth/sign-in"
# A failed response body is shown to explain the failure; a validation error can echo the input.
MAX_BODY_SHOWN = 300


class _TokenBody(BaseModel):
    # The aliases are the contract's field names (camelCase).
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")


@dataclass(frozen=True)
class AuthTokens:
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        """For a route guarded by the access token."""
        return {"Authorization": f"Bearer {self.access_token}"}

    @property
    def refresh_headers(self) -> dict[str, str]:
        """For the refresh route, the only one that accepts the refresh token."""
        return {"x-refresh-token": self.refresh_token}


async def sign_up(client: httpx.AsyncClient, email: str, password: str) -> AuthTokens:
    response = await client.post(
        SIGN_UP_PATH, json={"email": email, "password": password}
    )
    return _tokens(response, expected_status=201, action="sign-up")


async def sign_in(client: httpx.AsyncClient, email: str, password: str) -> AuthTokens:
    response = await client.post(
        SIGN_IN_PATH, json={"email": email, "password": password}
    )
    return _tokens(response, expected_status=200, action="sign-in")


def _tokens(
    response: httpx.Response, *, expected_status: int, action: str
) -> AuthTokens:
    # Fails the test with the cause; it never returns empty headers that would turn into a confusing 401 later.
    if response.status_code != expected_status:
        raise AssertionError(
            f"{action} answered {response.status_code}, expected {expected_status}: "
            f"{response.text[:MAX_BODY_SHOWN]}"
        )
    # A body of the wrong shape raises pydantic's ValidationError, which names the missing or mistyped field.
    body = _TokenBody.model_validate(response.json())
    return AuthTokens(access_token=body.access_token, refresh_token=body.refresh_token)
