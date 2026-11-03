"""FileAssertService.get_owned_file on a real Postgres. Task: 8.1."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import ForbiddenError
from app.models import Account, File
from app.services.file_assert import FileAssertService

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def service(session: AsyncSession) -> FileAssertService:
    return FileAssertService(session, Settings(database_url=None))


async def make_account(session: AsyncSession) -> str:
    account = Account(last_login_at=datetime.now(UTC).replace(tzinfo=None))
    session.add(account)
    await session.flush()
    return account.id


async def make_file(session: AsyncSession, owner_id: str) -> str:
    file = File(
        name="a.png",
        mime_type="image/png",
        size=3,
        created_by_id=owner_id,
        content=b"abc",
    )
    session.add(file)
    await session.flush()
    file_id = file.id
    # Out of the identity map: an object that is already loaded keeps its `content`.
    session.expunge_all()
    return file_id


async def test_the_owner_gets_the_file_without_its_bytes(
    db_session: AsyncSession,
) -> None:
    owner = await make_account(db_session)
    file_id = await make_file(db_session, owner)

    file = await service(db_session).get_owned_file(file_id, owner)

    assert (file.id, file.name, file.mime_type, file.size) == (
        file_id,
        "a.png",
        "image/png",
        3,
    )
    assert "content" in inspect(file).unloaded


async def test_another_accounts_file_is_forbidden(db_session: AsyncSession) -> None:
    owner = await make_account(db_session)
    other = await make_account(db_session)
    file_id = await make_file(db_session, owner)

    with pytest.raises(ForbiddenError):
        await service(db_session).get_owned_file(file_id, other)


async def test_an_unknown_file_is_forbidden_not_missing(
    db_session: AsyncSession,
) -> None:
    owner = await make_account(db_session)

    with pytest.raises(ForbiddenError):
        await service(db_session).get_owned_file(MISSING_ID, owner)


async def test_a_soft_deleted_file_is_forbidden(db_session: AsyncSession) -> None:
    owner = await make_account(db_session)
    file_id = await make_file(db_session, owner)
    await db_session.execute(
        update(File).where(File.id == file_id).values(deleted=True)
    )

    with pytest.raises(ForbiddenError):
        await service(db_session).get_owned_file(file_id, owner)
