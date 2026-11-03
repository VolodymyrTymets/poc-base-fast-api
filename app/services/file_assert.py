"""FileAssertService: the size and type of an upload, and who may touch a file. Ports the Node `FileAssertService`. Tasks: 8.1.

The shape of a service (class over a session, no commit) is ADR-0021. Differences from Node, on purpose: the size is the
number of received bytes (ENDPOINTS decision 10), so there is no client-supplied size and no stored-type fallback; a
soft-deleted file is not accessible (rule P6); an oversized upload is 413 and a bad type 422, not 403 (decision 6).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.config import Settings
from app.core.errors import (
    ErrorDetail,
    ForbiddenError,
    PayloadTooLargeError,
    ValidationFailedError,
)
from app.models import File

# `File.content` is left out: it holds up to FILE_MAX_SIZE bytes, and an async session cannot lazy-load it later.
_METADATA = (
    File.id,
    File.name,
    File.mime_type,
    File.size,
    File.created_by_id,
    File.created_at,
    File.updated_at,
    File.deleted,
)


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
        existence is not leaked (ENDPOINTS decision 3). Do not read `file.content` on the result: it is not loaded, and an
        async session cannot load it lazily. A caller that needs the bytes selects them itself (task 8.3).
        """
        result = await self._session.scalars(
            select(File)
            .where(
                File.id == file_id,
                File.created_by_id == account_id,
                File.deleted.is_(False),
            )
            .options(load_only(*_METADATA))
        )
        file = result.one_or_none()
        if file is None:
            raise ForbiddenError
        return file
