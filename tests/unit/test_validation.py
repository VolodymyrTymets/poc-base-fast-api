import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.validation import (
    CurrentPassword,
    Email,
    NewPassword,
    PhoneNumber,
    ProfileEmail,
    StrictModel,
    UuidStr,
)

VALID_UUID = "123e4567-e89b-12d3-a456-426614174000"
AT_LIMIT_ADDRESS = "a" * 64 + "@" + ".".join(["b" * 61] * 3) + ".com"  # 64+1+183+2+4
OVER_LIMIT_ADDRESS = "a@" + "b" * 250 + ".com"


def leaked_slices(value: str, text: str) -> list[str]:
    """The 4-character slices of `value` found in `text` (one letter alone is too weak a signal)."""
    slices = [value[i : i + 4] for i in range(len(value) - 3)]
    return [piece for piece in slices if piece in text]


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


@pytest.mark.parametrize("value", ["x", "a" * 72])
def test_current_password_accepts_one_to_72_bytes(value: str) -> None:
    assert TypeAdapter(CurrentPassword).validate_python(value) == value


@pytest.mark.parametrize(
    ("value", "kind"), [("", "password_too_short"), ("a" * 73, "password_too_long")]
)
def test_current_password_rejects_outside_one_to_72_bytes(
    value: str, kind: str
) -> None:
    assert error_types(TypeAdapter(CurrentPassword), value) == [kind]


def test_email_is_lowercased_after_validation() -> None:
    assert (
        TypeAdapter(Email).validate_python("Jane.Doe@Example.COM")
        == "jane.doe@example.com"
    )


@pytest.mark.parametrize(
    ("value", "kinds"),
    [
        (" a@b.com", ["email_invalid"]),
        ("a@b.com ", ["email_invalid"]),
        ("Name <a@b.com>", ["email_invalid"]),
        ("a@b", ["email_invalid"]),
        ("nope", ["email_invalid"]),
        (OVER_LIMIT_ADDRESS, ["string_too_long"]),
    ],
)
def test_email_rejects_malformed_padded_or_long_values(
    value: str, kinds: list[str]
) -> None:
    assert error_types(TypeAdapter(Email), value) == kinds


def test_email_at_the_254_character_limit_is_accepted() -> None:
    assert TypeAdapter(Email).validate_python(AT_LIMIT_ADDRESS) == AT_LIMIT_ADDRESS


def test_address_fixture_is_254_characters() -> None:
    assert len(AT_LIMIT_ADDRESS) == 254


def test_profile_email_accepts_a_domain_without_a_suffix() -> None:
    assert TypeAdapter(ProfileEmail).validate_python("A@B") == "a@b"


def test_email_refuses_the_same_domain_without_a_suffix() -> None:
    assert error_types(TypeAdapter(Email), "a@b") == ["email_invalid"]


@pytest.mark.parametrize("value", [" a@b", "a@b ", "Name <a@b>", "nope"])
def test_profile_email_still_rejects_malformed_values(value: str) -> None:
    assert error_types(TypeAdapter(ProfileEmail), value) == ["email_invalid"]


@pytest.mark.parametrize(
    ("value", "stored"),
    [("+12025550100", "+12025550100"), ("+1 202 555 0123", "+12025550123")],
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
        (TypeAdapter(ProfileEmail), "Zq7Xk9wv"),
        (TypeAdapter(PhoneNumber), "Zq7Xk9wv"),
        (TypeAdapter(UuidStr), "Zq7Xk9wv"),
    ],
)
def test_error_messages_never_contain_the_submitted_value(
    adapter: TypeAdapter[str], value: str
) -> None:
    with pytest.raises(ValidationError) as info:
        adapter.validate_python(value)

    text = " ".join(str(error["msg"]) for error in info.value.errors())
    assert leaked_slices(value, text) == []


class _Body(StrictModel):
    first_name: str


def test_strict_model_reads_camel_case_keys() -> None:
    assert _Body.model_validate({"firstName": "Ann"}).first_name == "Ann"


def test_strict_model_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError) as info:
        _Body.model_validate({"firstName": "Ann", "nickname": "x"})

    assert [str(e["type"]) for e in info.value.errors()] == ["extra_forbidden"]
