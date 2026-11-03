"""Every field of the profile update model must name a column of `AccountProfile`. Task: 5.4.

`AccountProfileService.update` copies the sent fields onto the profile by attribute name. A schema field with no column behind it
(or a protected one such as `is_phone_verified`) would otherwise be dropped silently or become client-writable without a review.
"""

from sqlalchemy import inspect

from app.models import AccountProfile
from app.schemas.account_profile import UpdateAccountProfileInput

# The columns a client may change through PATCH. Adding one here is a deliberate, reviewed step.
WRITABLE = {
    "first_name",
    "last_name",
    "middle_name",
    "date_of_birth",
    "email",
    "avatar_id",
}


def test_the_update_fields_are_exactly_the_writable_columns() -> None:
    assert set(UpdateAccountProfileInput.model_fields) == WRITABLE


def test_every_writable_field_is_a_column_of_the_profile() -> None:
    columns = {attr.key for attr in inspect(AccountProfile).column_attrs}

    assert WRITABLE <= columns
