"""FilesService on a real Postgres. Task: 8.2. The limits and the owner check are 8.1's, tested in test_db_file_assert_service.py."""

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.db import utc_now
from app.core.errors import PayloadTooLargeError, ValidationFailedError
from app.models import Account, File
from app.services.file_assert import FileAssertService
from app.services.files import FilesService

PNG = b"\x89PNG-bytes"


def service(session: AsyncSession, max_size: int = 1000) -> FilesService:
    settings = Settings(database_url=None, file_max_size=max_size)
    return FilesService(session, FileAssertService(session, settings))


async def make_account(session: AsyncSession) -> str:
    account = Account(last_login_at=utc_now())
    session.add(account)
    await session.flush()
    return account.id


async def stored(session: AsyncSession, file_id: str) -> tuple[bytes | None, int, str]:
    """The row as the database holds it, read past the session's identity map."""
    session.expunge_all()
    row = (
        await session.execute(
            select(File.content, File.size, File.mime_type).where(File.id == file_id)
        )
    ).one()
    return row.content, row.size, row.mime_type


async def file_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(File))).scalar_one()


async def test_create_stores_the_bytes_and_takes_size_and_type_from_the_upload(
    db_session: AsyncSession,
) -> None:
    # Arrange
    owner = await make_account(db_session)

    # Act
    file = await service(db_session).create(
        owner, PNG, "image/PNG; charset=x", "photo.png", None
    )

    # Assert
    assert (file.size, file.mime_type, file.created_by_id) == (
        len(PNG),
        "image/png",
        owner,
    )
    assert await stored(db_session, file.id) == (PNG, len(PNG), "image/png")


async def test_create_names_the_file_from_the_name_sent_or_else_the_filename(
    db_session: AsyncSession,
) -> None:
    # Arrange
    owner = await make_account(db_session)
    files = service(db_session)

    # Act
    named = await files.create(owner, PNG, "image/png", "photo.png", "Holiday")
    unnamed = await files.create(owner, PNG, "image/png", "photo.png", None)

    # Assert
    assert (named.name, unnamed.name) == ("Holiday", "photo.png")


@pytest.mark.parametrize("filename", ["a" * 256, "bad\x00name", "", None])
async def test_create_stores_no_name_for_a_filename_that_a_name_would_refuse(
    db_session: AsyncSession, filename: str | None
) -> None:
    # Arrange
    owner = await make_account(db_session)

    # Act
    file = await service(db_session).create(owner, PNG, "image/png", filename, None)

    # Assert
    assert file.name is None


@pytest.mark.parametrize(
    ("content", "mime_type", "error"),
    [
        (b"x" * 11, "image/png", PayloadTooLargeError),
        (PNG, "text/plain", ValidationFailedError),
        (PNG, None, ValidationFailedError),
    ],
)
async def test_a_failed_upload_check_stores_nothing(
    db_session: AsyncSession,
    content: bytes,
    mime_type: str | None,
    error: type[Exception],
) -> None:
    # Arrange
    owner = await make_account(db_session)

    # Act
    with pytest.raises(error):
        await service(db_session, max_size=10).create(
            owner, content, mime_type, "a.png", None
        )

    # Assert
    assert await file_count(db_session) == 0


async def test_update_with_only_a_name_keeps_the_bytes_size_and_type(
    db_session: AsyncSession,
) -> None:
    # Arrange
    owner = await make_account(db_session)
    files = service(db_session)
    created = await files.create(owner, PNG, "image/png", "a.png", None)

    # Act
    file = await files.update(created.id, owner, name="Renamed")

    # Assert
    assert file.name == "Renamed"
    assert await stored(db_session, created.id) == (PNG, len(PNG), "image/png")


async def test_update_with_a_file_replaces_bytes_size_and_type_together(
    db_session: AsyncSession,
) -> None:
    # Arrange
    owner = await make_account(db_session)
    files = service(db_session)
    created = await files.create(owner, PNG, "image/png", "a.png", "Keep")
    new_bytes = b"\xff\xd8\xff-jpeg"

    # Act
    file = await files.update(
        created.id, owner, content=new_bytes, mime_type="image/jpeg"
    )

    # Assert
    assert (file.name, file.size, file.mime_type) == (
        "Keep",
        len(new_bytes),
        "image/jpeg",
    )
    assert await stored(db_session, created.id) == (
        new_bytes,
        len(new_bytes),
        "image/jpeg",
    )


async def test_update_with_a_file_that_fails_the_limits_changes_nothing(
    db_session: AsyncSession,
) -> None:
    # Arrange
    owner = await make_account(db_session)
    files = service(db_session, max_size=20)
    created = await files.create(owner, PNG, "image/png", "a.png", None)

    # Act
    with pytest.raises(PayloadTooLargeError):
        await files.update(
            created.id, owner, name="Nope", content=b"x" * 21, mime_type="image/png"
        )

    # Assert
    assert await stored(db_session, created.id) == (PNG, len(PNG), "image/png")


async def test_get_returns_the_metadata_without_loading_the_bytes(
    db_session: AsyncSession,
) -> None:
    # Arrange
    owner = await make_account(db_session)
    files = service(db_session)
    created = await files.create(owner, PNG, "image/png", "a.png", None)
    db_session.expunge_all()

    # Act
    file = await files.get(created.id, owner)

    # Assert
    assert "content" in inspect(file).unloaded
    with pytest.raises(InvalidRequestError, match="content"):
        _ = file.content
