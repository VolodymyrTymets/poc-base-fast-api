"""The sample data of the seed items is valid input for the API it will be used with. No database. Task: 5.5."""

from pydantic import TypeAdapter

from app.core.validation import PhoneNumber, ProfileEmail
from app.schemas.account_profile import UpdateAccountProfileInput
from app.seeds.items.init_admin import ADMINS
from app.seeds.items.init_customer import CUSTOMERS

PHONES = [sample["phone_number"] for sample in [*ADMINS, *CUSTOMERS]]
EMAILS = [sample["email"] for sample in [*ADMINS, *CUSTOMERS]]


def test_every_sample_phone_is_a_valid_phone_number() -> None:
    adapter = TypeAdapter(PhoneNumber)

    assert [adapter.validate_python(phone) for phone in PHONES] == PHONES


def test_every_sample_email_is_a_valid_profile_email_already_normalised() -> None:
    adapter = TypeAdapter(ProfileEmail)

    assert [adapter.validate_python(email) for email in EMAILS] == EMAILS


def test_phones_and_emails_are_distinct() -> None:
    assert (len(set(PHONES)), len(set(EMAILS))) == (len(PHONES), len(EMAILS))


def test_every_sample_phone_is_in_the_range_reserved_for_fiction() -> None:
    # +1 212 555 01xx: NANP 555-0100 to 555-0199 never belongs to a real person.
    assert [phone[:9] for phone in PHONES] == ["+12125550"] * len(PHONES)
    assert all(100 <= int(phone[9:]) <= 199 for phone in PHONES)


def test_every_customer_profile_is_accepted_by_the_update_model() -> None:
    for sample in CUSTOMERS:
        UpdateAccountProfileInput.model_validate(
            {
                "firstName": sample["first_name"],
                "lastName": sample["last_name"],
                "middleName": sample["middle_name"],
                "email": sample["email"],
                "dataOfBirth": sample["date_of_birth"],
            }
        )


def test_no_sample_carries_an_ssn_or_a_password() -> None:
    keys = {key for sample in [*ADMINS, *CUSTOMERS] for key in sample}

    assert not keys & {"ssn", "SSN", "password", "is_18_year_old"}
