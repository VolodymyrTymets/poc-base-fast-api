from datetime import datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.validation import FileName
from app.schemas.files import FileMetadataResponse

FILE_ID = "123e4567-e89b-12d3-a456-426614174000"


class _Row:
    """Stands in for an ORM row, with the bytes attached to prove they are not copied."""

    id = FILE_ID
    name = "a.png"
    mime_type = "image/png"
    size = 3
    created_at = datetime(2026, 1, 1, 12, 0)
    content = b"\x89PN"


def test_the_response_uses_camel_case_names_and_a_content_url() -> None:
    # Arrange
    row = _Row()

    # Act
    body = FileMetadataResponse.model_validate(row).model_dump(
        by_alias=True, mode="json"
    )

    # Assert
    assert body == {
        "id": FILE_ID,
        "name": "a.png",
        "mimeType": "image/png",
        "size": 3,
        "createdAt": "2026-01-01T12:00:00",
        "contentUrl": f"/api/v1/files/{FILE_ID}/content",
    }


def test_the_response_has_no_field_for_the_bytes() -> None:
    assert "content" not in FileMetadataResponse.model_fields


def test_a_file_name_of_255_characters_is_valid() -> None:
    assert TypeAdapter(FileName).validate_python("a" * 255) == "a" * 255


@pytest.mark.parametrize(
    ("value", "error_type"),
    [("a" * 256, "string_too_long"), ("a\x00b", "control_character")],
)
def test_a_file_name_over_the_limits_is_rejected(value: str, error_type: str) -> None:
    with pytest.raises(ValidationError) as info:
        TypeAdapter(FileName).validate_python(value)

    assert [e["type"] for e in info.value.errors()] == [error_type]
