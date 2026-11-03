"""Models for the profile update. Request model: task 4.3; the response model: task 5.4."""

from typing import Annotated

from pydantic import Field, StringConstraints, field_validator
from pydantic_core import PydanticCustomError

from app.core.validation import ProfileEmail, StrictModel, UuidStr

ProfileName = Annotated[str, StringConstraints(max_length=50)]


class UpdateAccountProfileInput(StrictModel):
    """A field that is not sent stays unchanged; an explicit `null` clears a nullable one.

    Read `model_fields_set` to tell the two apart: both leave the attribute `None`.
    """

    first_name: ProfileName | None = None
    last_name: ProfileName | None = None
    middle_name: ProfileName | None = None
    # Holds text, not a date: the Node column "dataOfBirth" is a string of at most 10 characters.
    # The explicit alias wins over the camelCase generator, which would give `dateOfBirth`.
    date_of_birth: Annotated[str, StringConstraints(max_length=10)] | None = Field(
        default=None, alias="dataOfBirth"
    )
    email: ProfileEmail | None = None
    avatar_id: UuidStr | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _email_is_never_cleared(cls, value: object) -> object:
        # A profile always has an email; Node let `null` through to a 500 (ENDPOINTS.md, decision 18).
        if value is None:
            raise PydanticCustomError("null_not_allowed", "Must not be null")
        return value
