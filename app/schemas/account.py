"""Models for GET /account. Tasks: 5.3."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.schemas.account_profile import AccountProfileResponse


class AccountResponse(BaseModel):
    """The signed-in account with its profile. A fixed shape: no field selection (REST, ADR-0003)."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )

    id: str
    created_at: datetime
    updated_at: datetime | None
    profile: AccountProfileResponse | None
