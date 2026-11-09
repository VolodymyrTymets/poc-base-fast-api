"""Response model of the /files routes. Tasks: 8.2.

The request side is multipart form fields, declared on the routes: `name` uses `FileName` from `app/core/validation.py`.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field
from pydantic.alias_generators import to_camel


class FileMetadataResponse(BaseModel):
    """A file's metadata as the API shows it; the bytes are only ever served by `GET /files/{id}/content` (ADR-0009).

    It lists the fields one by one, so `File.content` can never reach a response.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )

    id: str
    name: str | None
    mime_type: str | None
    size: int
    created_at: datetime

    def _content_url(self) -> str:
        return f"/api/v1/files/{self.id}/content"

    # The function form of the decorator: mypy rejects `@computed_field` on top of `@property`.
    content_url = computed_field(return_type=str)(property(_content_url))
