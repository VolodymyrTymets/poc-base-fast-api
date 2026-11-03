"""Request models of the /auth routes (task 4.3). The response models come with tasks 7.1 to 7.6."""

from typing import Annotated

from pydantic import StringConstraints

from app.core.validation import (
    CurrentPassword,
    Email,
    NewPassword,
    PhoneNumber,
    StrictModel,
)


class OtpRequestInput(StrictModel):
    phone_number: PhoneNumber


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
