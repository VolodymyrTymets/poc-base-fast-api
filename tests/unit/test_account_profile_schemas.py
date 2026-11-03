import pytest
from pydantic import ValidationError

from app.schemas.account_profile import UpdateAccountProfileInput

AVATAR = "123e4567-e89b-12d3-a456-426614174000"


def test_a_field_that_is_not_sent_is_unset() -> None:
    body = UpdateAccountProfileInput.model_validate({"firstName": "Ann"})

    assert body.model_fields_set == {"first_name"}


def test_an_explicit_null_clears_a_nullable_field_and_counts_as_sent() -> None:
    body = UpdateAccountProfileInput.model_validate(
        {"middleName": None, "avatarId": None}
    )

    assert body.model_fields_set == {"middle_name", "avatar_id"}
    assert (body.middle_name, body.avatar_id) == (None, None)


def test_a_null_email_is_rejected() -> None:
    with pytest.raises(ValidationError) as info:
        UpdateAccountProfileInput.model_validate({"email": None})

    assert [(e["loc"], e["type"]) for e in info.value.errors()] == [
        (("email",), "null_not_allowed")
    ]


def test_valid_values_are_normalised() -> None:
    body = UpdateAccountProfileInput.model_validate(
        {
            "email": "Ann@Example.com",
            "avatarId": AVATAR.upper(),
            "dataOfBirth": "1990-01-31",
        }
    )

    assert (body.email, body.avatar_id, body.date_of_birth) == (
        "ann@example.com",
        AVATAR,
        "1990-01-31",
    )


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"firstName": "a" * 51}, "firstName"),
        ({"lastName": "a" * 51}, "lastName"),
        ({"middleName": "a" * 51}, "middleName"),
        ({"dataOfBirth": "1990-01-311"}, "dataOfBirth"),
        ({"avatarId": "not-a-uuid"}, "avatarId"),
        ({"ssn": "123"}, "ssn"),
        ({"is18YearOld": True}, "is18YearOld"),
    ],
)
def test_limits_and_unknown_keys_name_the_field(
    body: dict[str, object], field: str
) -> None:
    with pytest.raises(ValidationError) as info:
        UpdateAccountProfileInput.model_validate(body)

    assert [e["loc"] for e in info.value.errors()] == [(field,)]
