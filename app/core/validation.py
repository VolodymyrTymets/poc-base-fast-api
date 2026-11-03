"""Request validation primitives: the strict base model and the reusable field types. Tasks: 4.3 (ADR-0003).

Request models in `app/schemas/` inherit `StrictModel` and use these types, so every route
agrees on what a valid email, password, phone number or UUID is.

Failures raise `PydanticCustomError` with our own `type` and a fixed message. Pydantic's built-in
messages can echo a character of the input (a bad UUID does), and a password or phone number must
never reach a response or a log (rules D8, P4); `validation_details` in `core/errors.py` reads only
`loc`, `msg` and `type`, so a message written here must never contain the value.
"""

import unicodedata
import uuid
from typing import Annotated

import phonenumbers
from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError

EMAIL_MAX_LENGTH = 254
PASSWORD_MAX_BYTES = 72
NEW_PASSWORD_MIN_BYTES = 8


class StrictModel(BaseModel):
    """Base of every request model: unknown keys are a 422, the wire names are camelCase."""

    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, populate_by_name=True
    )


def _byte_length(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        # A lone surrogate (JSON "\ud800") is not text; without this it would end as a 500.
        raise PydanticCustomError("invalid_text", "Must be valid UTF-8 text") from None


def _reject_control_characters(value: str) -> None:
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise PydanticCustomError(
            "control_character", "Must not contain control characters"
        )


def _check_password_bytes(value: str, minimum: int) -> str:
    size = _byte_length(value)
    if size < minimum:
        raise PydanticCustomError(
            "password_too_short",
            "Must be at least {minimum} bytes",
            {"minimum": minimum},
        )
    if size > PASSWORD_MAX_BYTES:
        # 72 bytes is what bcrypt reads (rule P5 note): more would be silently truncated.
        raise PydanticCustomError(
            "password_too_long",
            "Must be at most {maximum} bytes",
            {"maximum": PASSWORD_MAX_BYTES},
        )
    return value


def _new_password(value: str) -> str:
    _check_password_bytes(value, NEW_PASSWORD_MIN_BYTES)
    _reject_control_characters(value)
    return value


def _current_password(value: str) -> str:
    # Looser than a new password: an account made under older rules must still sign in.
    return _check_password_bytes(value, 1)


def _email(value: str) -> str:
    # Validated as sent (an address with surrounding spaces is rejected, as in Node), then
    # lowercased: the whole address is normalised before lookup and storage.
    try:
        result = validate_email(value, check_deliverability=False)
    except EmailNotValidError:
        # The library's message quotes the input, so it is dropped.
        raise PydanticCustomError(
            "email_invalid", "Must be a valid email address"
        ) from None
    return result.normalized.lower()


def _phone_number(value: str) -> str:
    # `parse(value, None)` needs the leading "+"; a national number has no region to read.
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException:
        raise PydanticCustomError(
            "phone_invalid", "Must be a valid phone number in international format"
        ) from None
    if not phonenumbers.is_valid_number(parsed):
        raise PydanticCustomError(
            "phone_invalid", "Must be a valid phone number in international format"
        )
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise PydanticCustomError("uuid_invalid", "Must be a valid UUID") from None


# The length limits count characters; the byte limits of the passwords are in the validators.
Email = Annotated[
    str, StringConstraints(max_length=EMAIL_MAX_LENGTH), AfterValidator(_email)
]
NewPassword = Annotated[str, AfterValidator(_new_password)]
CurrentPassword = Annotated[str, AfterValidator(_current_password)]
PhoneNumber = Annotated[str, AfterValidator(_phone_number)]
UuidStr = Annotated[str, AfterValidator(_uuid)]
