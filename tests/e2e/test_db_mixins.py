from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import MetaData, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped

from app.config import Settings
from app.core.db import (
    NAMING_CONVENTION,
    IdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    create_engine,
    create_session_factory,
    utc_now,
)


# Its own base, so the real Base.metadata stays empty for Alembic (2.4).
class MixinBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class MixinProbe(IdMixin, TimestampMixin, SoftDeleteMixin, MixinBase):
    __tablename__ = "PocMixinProbe"
    name: Mapped[str]


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """The engine the app builds, with the probe table made and dropped around the test."""
    engine = create_engine(Settings(database_url=database_url))
    assert engine is not None
    async with engine.begin() as connection:
        await connection.run_sync(MixinBase.metadata.drop_all)
        await connection.run_sync(MixinBase.metadata.create_all)
    yield engine
    async with engine.begin() as connection:
        await connection.run_sync(MixinBase.metadata.drop_all)
    await engine.dispose()


async def test_an_insert_fills_the_id_the_flag_and_both_timestamps(
    engine: AsyncEngine,
) -> None:
    factory = create_session_factory(engine)

    async with factory() as session:
        session.add(MixinProbe(name="first"))
        await session.commit()
    async with factory() as session:
        row = (await session.execute(select(MixinProbe))).scalar_one()

    assert (len(row.id), row.deleted) == (36, False)
    assert row.updated_at is not None


async def test_created_at_comes_from_the_database_in_utc(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    before = utc_now()

    async with factory() as session:
        session.add(MixinProbe(name="clock"))
        await session.commit()
    async with factory() as session:
        row = (await session.execute(select(MixinProbe))).scalar_one()

    # A session in the server's own zone (Europe/Kiev here) would be hours off.
    assert abs(row.created_at - before) < timedelta(minutes=1)


async def test_an_update_moves_updated_at_forward(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    old = datetime(2000, 1, 1, tzinfo=UTC).replace(tzinfo=None)

    async with factory() as session:
        session.add(MixinProbe(name="before", updated_at=old))
        await session.commit()
    async with factory() as session:
        await _rename(session, "after")
        row = (await session.execute(select(MixinProbe))).scalar_one()

    assert (row.name, row.updated_at is not None and row.updated_at > old) == (
        "after",
        True,
    )


async def _rename(session: AsyncSession, name: str) -> None:
    await session.execute(update(MixinProbe).values(name=name))
    await session.commit()
