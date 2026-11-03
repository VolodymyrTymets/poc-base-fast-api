"""FileAssertService: the size and type of an upload, and who may touch a file. Ports the Node `FileAssertService`. Tasks: 8.1.

The shape of a service (class over a session, no commit) is ADR-0021. Differences from Node, on purpose: the size is the
number of received bytes (ENDPOINTS decision 10), so there is no client-supplied size and no stored-type fallback; a
soft-deleted file is not accessible (rule P6); an oversized upload is 413 and a bad type 422, not 403 (decision 6).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.config import Settings
from app.core.errors import (
    ErrorDetail,
    ForbiddenError,
    PayloadTooLargeError,
    ValidationFailedError,
)
from app.models import File


def _upload_detail(message: str, error_type: str) -> list[ErrorDetail]:
    # Fixed text only: never the file name, the bytes or the submitted type (rules D8, P4).
    return [{"in": "body", "field": "file", "message": message, "type": error_type}]


def _media_type(mime_type: str) -> str:
    # `image/PNG; charset=x` is the type `image/png`.
    return mime_type.split(";", 1)[0].strip().lower()


class FileAssertService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._max_size = settings.file_max_size
        self._allowed_mime_types = frozenset(settings.file_allowed_mime_types)

    def assert_upload(self, size: int, mime_type: str | None) -> None:
        """Raise unless an upload of `size` bytes declared as `mime_type` is allowed: 413 over the limit, 422 for a missing or disallowed type."""
        if size < 0:
            raise ValueError("size is a byte count and cannot be negative")
        if size > self._max_size:
            raise PayloadTooLargeError(
                details=_upload_detail("File is too large", "file_too_large")
            )
        if not mime_type or _media_type(mime_type) not in self._allowed_mime_types:
            raise ValidationFailedError(
                details=_upload_detail(
                    "File type is not allowed", "file_type_not_allowed"
                )
            )

    async def get_owned_file(self, file_id: str, account_id: str) -> File:
        """The file the account created, with its metadata and without its bytes.

        An unknown id, another account's file and a soft-deleted file are the same `ForbiddenError`, so a file's
        existence is not leaked (ENDPOINTS decision 3). `content` (up to FILE_MAX_SIZE bytes) is deferred with `raiseload`:
        reading `file.content` on the result raises instead of loading, and every other column loads, so a column added
        later is not silently missing. A caller that needs the bytes selects them itself (task 8.3).
        """
        result = await self._session.scalars(
            select(File)
            .where(
                File.id == file_id,
                File.created_by_id == account_id,
                File.deleted.is_(False),
            )
            .options(defer(File.content, raiseload=True))
        )
        file = result.one_or_none()
        if file is None:
            raise ForbiddenError
        return file
