import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.validation import (
    CurrentPassword,
    Email,
    NewPassword,
    PhoneNumber,
    StrictModel,
    UuidStr,
)

VALID_UUID = "123e4567-e89b-12d3-a456-426614174000"


def error_types(adapter: TypeAdapter[str], value: object) -> list[str]:
    with pytest.raises(ValidationError) as info:
        adapter.validate_python(value)
    return [str(error["type"]) for error in info.value.errors()]


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("a" * 7, "password_too_short"),
        ("a" * 73, "password_too_long"),
        ("é" * 40, "password_too_long"),  # 40 characters, 80 bytes
        ("pass\tword", "control_character"),
        ("pass\nword", "control_character"),
        ("pass\x00word", "control_character"),
        ("\ud800" * 9, "invalid_text"),
    ],
)
def test_new_password_rejects(value: str, kind: str) -> None:
    assert error_types(TypeAdapter(NewPassword), value) == [kind]


@pytest.mark.parametrize("value", ["a" * 8, "a" * 72, "é" * 36, "pässwörd with spaces"])
def test_new_password_accepts_the_byte_range(value: str) -> None:
    assert TypeAdapter(NewPassword).validate_python(value) == value


def test_current_password_takes_one_to_72_bytes() -> None:
    adapter = TypeAdapter(CurrentPassword)

    assert adapter.validate_python("x") == "x"
    assert error_types(adapter, "") == ["password_too_short"]
    assert error_types(adapter, "a" * 73) == ["password_too_long"]


def test_email_is_lowercased_after_validation() -> None:
    assert (
        TypeAdapter(Email).validate_python("Jane.Doe@Example.COM")
        == "jane.doe@example.com"
    )


@pytest.mark.parametrize(
    "value",
    [
        " a@b.com",
        "a@b.com ",
        "Name <a@b.com>",
        "a@b",
        "nope",
        "a@" + "b" * 250 + ".com",
    ],
)
def test_email_rejects_malformed_or_padded_or_long_values(value: str) -> None:
    assert error_types(TypeAdapter(Email), value)


def test_email_at_the_254_character_limit_is_not_rejected_for_length() -> None:
    local = "a" * 64
    domain = ".".join(["b" * 61] * 3) + ".com"  # 64 + 1 + 183 + 2 + 4 = 254
    address = f"{local}@{domain}"
    assert len(address) == 254

    assert TypeAdapter(Email).validate_python(address) == address


@pytest.mark.parametrize(
    ("value", "stored"),
    [("+380671234567", "+380671234567"), ("+1 202 555 0123", "+12025550123")],
)
def test_phone_is_stored_as_e164(value: str, stored: str) -> None:
    assert TypeAdapter(PhoneNumber).validate_python(value) == stored


@pytest.mark.parametrize("value", ["380671234567", "+12", "abc", "", "+1 202 555"])
def test_phone_rejects_what_is_not_international(value: str) -> None:
    assert error_types(TypeAdapter(PhoneNumber), value) == ["phone_invalid"]


def test_uuid_is_returned_in_canonical_form() -> None:
    assert TypeAdapter(UuidStr).validate_python(VALID_UUID.upper()) == VALID_UUID


@pytest.mark.parametrize("value", ["zzz", "", VALID_UUID + "0"])
def test_uuid_rejects_other_strings(value: str) -> None:
    assert error_types(TypeAdapter(UuidStr), value) == ["uuid_invalid"]


@pytest.mark.parametrize(
    ("adapter", "value"),
    [
        (TypeAdapter(NewPassword), "Zq7Xk9wv\t"),
        (TypeAdapter(NewPassword), "Zq7Xk9"),
        (TypeAdapter(Email), "Zq7Xk9wv"),
        (TypeAdapter(PhoneNumber), "Zq7Xk9wv"),
        (TypeAdapter(UuidStr), "Zq7Xk9wv"),
    ],
)
def test_error_messages_never_contain_the_submitted_value(
    adapter: TypeAdapter[str], value: str
) -> None:
    with pytest.raises(ValidationError) as info:
        adapter.validate_python(value)

    # The first letter alone would leak, so look for any 4-character slice of the input.
    text = " ".join(str(error["msg"]) for error in info.value.errors())
    leaked = [
        value[i : i + 4] for i in range(len(value) - 3) if value[i : i + 4] in text
    ]
    assert leaked == []


def test_strict_model_rejects_unknown_keys_and_reads_camel_case() -> None:
    class Body(StrictModel):
        first_name: str

    assert Body.model_validate({"firstName": "Ann"}).first_name == "Ann"
    with pytest.raises(ValidationError) as info:
        Body.model_validate({"firstName": "Ann", "nickname": "x"})
    assert [str(e["type"]) for e in info.value.errors()] == ["extra_forbidden"]
