"""FileAssertService.assert_upload: the size and type rules, with no database (an unbound session does no I/O). Task: 8.1."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import PayloadTooLargeError, ValidationFailedError
from app.services.file_assert import FileAssertService

LIMIT = 1000


def service() -> FileAssertService:
    settings = Settings(
        file_max_size=LIMIT,
        file_allowed_mime_types=["image/jpeg", "image/png"],
        database_url=None,
    )
    return FileAssertService(AsyncSession(), settings)


def test_a_size_at_the_limit_with_an_allowed_type_passes() -> None:
    service().assert_upload(LIMIT, "image/png")


def test_a_size_over_the_limit_is_413_naming_the_file_field() -> None:
    with pytest.raises(PayloadTooLargeError) as caught:
        service().assert_upload(LIMIT + 1, "image/png")

    assert caught.value.status_code == 413
    assert caught.value.details == [
        {
            "in": "body",
            "field": "file",
            "message": "File is too large",
            "type": "file_too_large",
        }
    ]


@pytest.mark.parametrize(
    "mime_type", ["IMAGE/PNG", "image/png; charset=binary", " image/jpeg "]
)
def test_the_type_match_ignores_case_and_parameters(mime_type: str) -> None:
    service().assert_upload(10, mime_type)


@pytest.mark.parametrize("mime_type", [None, "", "  ", "application/pdf", "image/gif"])
def test_a_missing_or_disallowed_type_is_422(mime_type: str | None) -> None:
    with pytest.raises(ValidationFailedError) as caught:
        service().assert_upload(10, mime_type)

    assert caught.value.status_code == 422
    assert caught.value.details == [
        {
            "in": "body",
            "field": "file",
            "message": "File type is not allowed",
            "type": "file_type_not_allowed",
        }
    ]


def test_the_error_never_holds_the_submitted_type() -> None:
    submitted = "application/x-secret-7731"

    with pytest.raises(ValidationFailedError) as caught:
        service().assert_upload(10, submitted)

    assert "7731" not in str(caught.value)
    assert "7731" not in repr(caught.value.details)


def test_an_empty_upload_passes_the_size_check() -> None:
    # "A file is required" is the router's 422 (task 8.2), not this layer's.
    service().assert_upload(0, "image/png")
