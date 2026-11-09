"""FilesService: create, rename, replace and read a file's metadata. Ports the Node `FilesService`. Tasks: 8.2 (the size, type and owner checks are services/file_assert.py, task 8.1).

The shape of a service (class over a session, flush but never commit) is ADR-0021. Differences from Node, on purpose
(ENDPOINTS decision 10): a file is created with its bytes, and its size and mime type come from the upload, never from the client.
"""

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation import FileName
from app.models import File
from app.services.file_assert import FileAssertService, media_type

_FILE_NAME = TypeAdapter(FileName)


def _name_or_filename(name: str | None, filename: str | None) -> str | None:
    """The name sent by the client; without one, the upload's filename if it passes the `FileName` limits, else `None`.

    A filename comes from the client's disk and is not checked by the route, so a long one or one with control characters
    is dropped rather than stored (a `name` with the same text would have been refused).
    """
    if name:
        return name
    if not filename:
        return None
    try:
        return _FILE_NAME.validate_python(filename)
    except ValidationError:
        return None


class FilesService:
    def __init__(self, session: AsyncSession, file_assert: FileAssertService) -> None:
        self._session = session
        self._file_assert = file_assert

    async def create(
        self,
        account_id: str,
        content: bytes,
        mime_type: str | None,
        filename: str | None,
        name: str | None,
    ) -> File:
        """Store an upload for `account_id` and flush; the caller commits (ADR-0021).

        Raises `PayloadTooLargeError` or `ValidationFailedError` (8.1) before anything is written.
        """
        self._file_assert.assert_upload(len(content), mime_type)
        file = File(
            name=_name_or_filename(name, filename),
            mime_type=media_type(mime_type or ""),
            size=len(content),
            created_by_id=account_id,
            content=content,
        )
        self._session.add(file)
        await self._session.flush()
        return file

    async def update(
        self,
        file_id: str,
        account_id: str,
        *,
        name: str | None = None,
        content: bytes | None = None,
        mime_type: str | None = None,
    ) -> File:
        """Rename the caller's file and/or replace its bytes, size and mime type together, and flush; the caller commits.

        `ForbiddenError` for an unknown, foreign or soft-deleted file (checked first, so a stranger learns nothing about
        the limits); a new `content` is checked against the limits again before anything is changed. A `name` of `None`
        means "not sent": a name cannot be cleared.
        """
        file = await self._file_assert.get_owned_file(file_id, account_id)
        if content is not None:
            self._file_assert.assert_upload(len(content), mime_type)
            file.content = content
            file.size = len(content)
            file.mime_type = media_type(mime_type or "")
        if name:
            file.name = name
        await self._session.flush()
        return file

    async def get(self, file_id: str, account_id: str) -> File:
        """The caller's file with its metadata and without its bytes (`ForbiddenError` as in `update`)."""
        return await self._file_assert.get_owned_file(file_id, account_id)
