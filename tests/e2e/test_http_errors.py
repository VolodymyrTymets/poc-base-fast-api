import logging
from typing import Literal

import httpx
import pytest
from fastapi import FastAPI
from fastapi import HTTPException as FastAPIHTTPException
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException
from utils.client import running_client

from app.config import Settings
from app.core.errors import (
    AppError,
    EmailAlreadyRegisteredError,
    ForbiddenError,
    InvalidCredentialsError,
    InvalidResetTokenError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.main import create_app

# A fake value, short enough to fail the min_length of SignUp below.
SUBMITTED_VALUE = "hunter2"
INTERNAL_MESSAGE = "secret-internal-detail"


class SignUp(BaseModel):
    email: str
    password: str = Field(min_length=8)


class Coupon(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def must_be_known(cls, value: str) -> str:
        # What task 4.3 validators will do: put the value in the error text.
        raise ValueError(f"unknown code {value}")


class Profile(BaseModel):
    email: str


class Account(BaseModel):
    profile: Profile


RAISED: dict[str, type[AppError]] = {
    "unauthorized": UnauthorizedError,
    "invalid-credentials": InvalidCredentialsError,
    "invalid-reset-token": InvalidResetTokenError,
    "email-already-registered": EmailAlreadyRegisteredError,
    "forbidden": ForbiddenError,
    "not-found": NotFoundError,
    "validation-failed": ValidationFailedError,
}


def make_app(app_env: Literal["local", "test", "production"] = "test") -> FastAPI:
    app = create_app(Settings(app_env=app_env))

    # The app has no route that raises yet, so the test adds its own to this instance.
    @app.get("/api/v1/_raise/{name}")
    async def raise_domain_error(name: str) -> None:
        raise RAISED[name]()

    @app.get("/api/v1/_http/{status}")
    async def raise_http_error(status: int) -> None:
        raise HTTPException(status_code=status, headers={"x-extra": "kept"})

    @app.get("/api/v1/_boom")
    async def boom() -> None:
        raise RuntimeError(INTERNAL_MESSAGE)

    @app.post("/api/v1/_sign-up")
    async def sign_up(payload: SignUp) -> None:
        return None

    @app.post("/api/v1/_coupon")
    async def coupon(payload: Coupon) -> None:
        return None

    @app.get("/api/v1/_http-detail")
    async def raise_http_detail() -> None:
        # FastAPI's class accepts any `detail`; Starlette's types it as a string.
        raise FastAPIHTTPException(status_code=400, detail={"k": "v"})

    @app.post("/api/v1/_account")
    async def account(payload: Account) -> None:
        return None

    return app


async def call(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, object] | None = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    # raise_app_exceptions=False: ServerErrorMiddleware re-raises after it has answered 500,
    # and a real server would not hand that to the client.
    async with running_client(app, raise_app_exceptions=False) as client:
        return await client.request(
            method, path, json=json, content=content, headers=headers
        )


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("unauthorized", 401, "UNAUTHORIZED"),
        ("invalid-credentials", 401, "INVALID_CREDENTIALS"),
        ("invalid-reset-token", 400, "INVALID_RESET_TOKEN"),
        ("email-already-registered", 409, "EMAIL_ALREADY_REGISTERED"),
        ("forbidden", 403, "FORBIDDEN"),
        ("not-found", 404, "NOT_FOUND"),
        ("validation-failed", 422, "VALIDATION_FAILED"),
    ],
)
async def test_domain_error_answers_with_its_status_and_code(
    name: str, status: int, code: str
) -> None:
    response = await call(make_app(), "GET", f"/api/v1/_raise/{name}")

    assert (response.status_code, response.json()) == (
        status,
        {
            "error": {
                "code": code,
                "message": RAISED[name].default_message,
                "details": [],
            }
        },
    )


async def test_bad_body_is_validation_failed_with_one_entry_per_field() -> None:
    response = await call(
        make_app(), "POST", "/api/v1/_sign-up", json={"password": SUBMITTED_VALUE}
    )

    body = response.json()
    assert response.status_code == 422
    assert "detail" not in body
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert {(d["in"], d["field"]) for d in body["error"]["details"]} == {
        ("body", "email"),
        ("body", "password"),
    }


async def test_nested_field_is_a_dotted_path() -> None:
    response = await call(make_app(), "POST", "/api/v1/_account", json={"profile": {}})

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == [
        "profile.email"
    ]


async def test_malformed_json_is_validation_failed() -> None:
    response = await call(
        make_app(),
        "POST",
        "/api/v1/_sign-up",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert (response.status_code, response.json()["error"]["details"]) == (
        422,
        [
            {
                "in": "body",
                "field": "",
                "message": "JSON decode error",
                "type": "json_invalid",
            }
        ],
    )


async def test_validator_message_that_contains_the_value_is_not_returned() -> None:
    response = await call(
        make_app(), "POST", "/api/v1/_coupon", json={"code": "SECRET123"}
    )

    assert response.status_code == 422
    assert "SECRET123" not in response.text
    assert response.json()["error"]["details"] == [
        {
            "in": "body",
            "field": "code",
            "message": "Invalid value",
            "type": "value_error",
        }
    ]


async def test_validation_error_never_echoes_the_submitted_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await call(
            make_app(),
            "POST",
            "/api/v1/_sign-up",
            json={"email": "a@example.test", "password": SUBMITTED_VALUE},
        )

    assert response.status_code == 422
    assert SUBMITTED_VALUE not in response.text
    assert SUBMITTED_VALUE not in caplog.text


async def test_unknown_path_is_not_found_in_the_contract_shape() -> None:
    response = await call(make_app(), "GET", "/api/v1/nothing-here")

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "NOT_FOUND",
    )


async def test_wrong_method_keeps_405_and_the_allow_header() -> None:
    response = await call(make_app(), "POST", "/api/v1/health")

    assert (response.status_code, response.json()["error"]["code"]) == (
        405,
        "VALIDATION_FAILED",
    )
    assert response.headers["allow"] == "GET"


@pytest.mark.parametrize(
    ("status", "code"), [(401, "UNAUTHORIZED"), (403, "FORBIDDEN"), (404, "NOT_FOUND")]
)
async def test_http_exception_with_a_known_status_gets_its_code(
    status: int, code: str
) -> None:
    response = await call(make_app(), "GET", f"/api/v1/_http/{status}")

    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert response.headers["x-extra"] == "kept"


async def test_unexpected_error_hides_the_trace_outside_local() -> None:
    response = await call(make_app("production"), "GET", "/api/v1/_boom")

    body = response.json()
    assert (response.status_code, body["error"]["code"]) == (
        500,
        "INTERNAL_SERVER_ERROR",
    )
    assert body["error"]["details"] == []
    assert INTERNAL_MESSAGE not in response.text
    assert "RuntimeError" not in response.text


async def test_unexpected_error_shows_the_trace_in_local() -> None:
    response = await call(make_app("local"), "GET", "/api/v1/_boom")

    (trace,) = response.json()["error"]["details"]
    assert response.status_code == 500
    assert "RuntimeError: secret-internal-detail" in trace


@pytest.mark.parametrize("app_env", ["local", "production"])
async def test_unexpected_error_is_logged_with_its_stack(
    app_env: Literal["local", "production"], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        await call(make_app(app_env), "GET", "/api/v1/_boom")

    (record,) = [r for r in caplog.records if r.name == "app.core.errors"]
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


async def test_http_exception_with_a_non_string_detail_still_has_a_string_message() -> (
    None
):
    response = await call(make_app(), "GET", "/api/v1/_http-detail")

    assert (response.status_code, response.json()) == (
        400,
        {
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "Bad Request",
                "details": [],
            }
        },
    )


async def test_not_modified_is_sent_without_a_body() -> None:
    response = await call(make_app(), "GET", "/api/v1/_http/304")

    assert (response.status_code, response.content) == (304, b"")
