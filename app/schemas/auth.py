"""Request models of the /auth routes (task 4.3) and their response models, which arrive with tasks 7.1 to 7.6 (7.1: `OtpRequestResponse`; 7.2: `TokenResponse`)."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic.alias_generators import to_camel

from app.core.validation import (
    CurrentPassword,
    Email,
    NewPassword,
    PhoneNumber,
    StrictModel,
)


class OtpRequestInput(StrictModel):
    phone_number: PhoneNumber


class OtpRequestResponse(BaseModel):
    """`{success, code?}`: `code` is present only in local, development and test, and the route leaves the key out otherwise."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    success: bool
    code: str | None = None


class TokenResponse(BaseModel):
    """`{accessToken, refreshToken}`, the answer of every successful sign-in (7.2 now; 7.3 and 7.4 reuse it)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    access_token: str
    refresh_token: str


class OtpVerifyInput(StrictModel):
    phone_number: PhoneNumber
    code: Annotated[str, StringConstraints(max_length=6)]


class SignUpInput(StrictModel):
    email: Email
    password: NewPassword


class SignInInput(StrictModel):
    email: Email
    password: CurrentPassword


class ChangePasswordInput(StrictModel):
    current_password: CurrentPassword
    new_password: NewPassword


class RestorePasswordInput(StrictModel):
    email: Email


class ResetPasswordInput(StrictModel):
    token: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: NewPassword
