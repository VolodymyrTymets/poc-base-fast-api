import pytest
from utils.client import running_client

from app.config import Settings
from app.main import create_app
from app.schemas.auth import SignUpInput

# Fake values; the password is short enough to fail the 8-byte minimum.
SUBMITTED_VALUE = "Zq7Xk9w"


async def test_a_bad_sign_up_body_names_every_bad_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(Settings())

    @app.post("/test-only/sign-up")
    async def sign_up(body: SignUpInput) -> dict[str, str]:
        return {"email": body.email}

    async with running_client(app) as client:
        response = await client.post(
            "/test-only/sign-up",
            json={"email": "nope", "password": SUBMITTED_VALUE, "admin": True},
        )

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert {d["field"] for d in body["error"]["details"]} == {
        "email",
        "password",
        "admin",
    }
    assert SUBMITTED_VALUE not in response.text
    assert SUBMITTED_VALUE not in caplog.text


async def test_a_valid_sign_up_body_reaches_the_handler_with_a_lowercased_email() -> (
    None
):
    app = create_app(Settings())

    @app.post("/test-only/sign-up")
    async def sign_up(body: SignUpInput) -> dict[str, str]:
        return {"email": body.email}

    async with running_client(app) as client:
        response = await client.post(
            "/test-only/sign-up",
            json={"email": "Ann@Example.com", "password": "longenough"},
        )

    assert (response.status_code, response.json()) == (
        200,
        {"email": "ann@example.com"},
    )
