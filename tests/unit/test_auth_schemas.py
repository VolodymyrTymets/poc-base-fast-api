from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from app.core.validation import StrictModel
from app.schemas.auth import (
    ChangePasswordInput,
    OtpVerifyInput,
    ResetPasswordInput,
    SignInInput,
    SignUpInput,
)


def failed_fields(model: type[StrictModel], body: Mapping[str, object]) -> set[str]:
    with pytest.raises(ValidationError) as info:
        model.model_validate(body)
    return {str(error["loc"][0]) for error in info.value.errors()}


def test_sign_up_parses_camel_case_and_normalises_the_email() -> None:
    body = SignUpInput.model_validate(
        {"email": "Ann@Example.com", "password": "longenough"}
    )

    assert (body.email, body.password) == ("ann@example.com", "longenough")


def test_sign_up_names_every_bad_field_and_the_unknown_key() -> None:
    fields = failed_fields(
        SignUpInput, {"email": "nope", "password": "short", "admin": True}
    )

    assert fields == {"email", "password", "admin"}


def test_sign_in_accepts_a_short_password() -> None:
    body = SignInInput.model_validate({"email": "a@b.com", "password": "x"})

    assert len(body.password) == 1


def test_sign_up_refuses_the_same_short_password() -> None:
    assert failed_fields(SignUpInput, {"email": "a@b.com", "password": "x"}) == {
        "password"
    }


def test_change_password_checks_the_new_password_only_for_strength() -> None:
    body = {"currentPassword": "x", "newPassword": "short"}

    assert failed_fields(ChangePasswordInput, body) == {"newPassword"}


@pytest.mark.parametrize("token", ["", "t" * 201])
def test_reset_password_token_must_be_one_to_200_characters(token: str) -> None:
    body = {"token": token, "newPassword": "longenough"}

    assert failed_fields(ResetPasswordInput, body) == {"token"}


def test_otp_verify_stores_the_phone_as_e164() -> None:
    ok = OtpVerifyInput.model_validate(
        {"phoneNumber": "+1 202 555 0123", "code": "123456"}
    )

    assert ok.phone_number == "+12025550123"


def test_otp_verify_code_is_at_most_six_characters() -> None:
    body = {"phoneNumber": "+12025550123", "code": "1234567"}

    assert failed_fields(OtpVerifyInput, body) == {"code"}
