"""Async engine, the request-scoped session dependency, the declarative Base and the column mixins. Tasks: 2.1."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import MetaData, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import Settings

# The names Prisma gives its constraints (ADR-0014), so the parity diff of task 2.5 has less
# to explain. A mixed-case table or column name is quoted by SQLAlchemy on its own.
NAMING_CONVENTION = {
    "pk": "%(table_name)s_pkey",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
}


class Base(DeclarativeBase):
    """Base of every model in app/models; Alembic (2.4) reads its metadata."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> str:
    """A uuid4 string, generated here because Prisma's `uuid(4)` is client-side too."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    # Naive on purpose: the columns are `timestamp without time zone` (as Prisma emits
    # them) and asyncpg refuses an aware datetime for such a column. The value is UTC.
    return datetime.now(UTC).replace(tzinfo=None)


# The mixins are opt-in (ADR-0014): a table takes only the columns its Prisma model has.
class IdMixin:
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP(precision=3),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    # Nullable in the database like Prisma's `DateTime? @updatedAt`, but filled on insert
    # and on every update, which is what Prisma's client does.
    updated_at: Mapped[datetime | None] = mapped_column(
        "updatedAt", TIMESTAMP(precision=3), default=utc_now, onupdate=utc_now
    )


class SoftDeleteMixin:
    # Rule P6: rows are flagged, never deleted.
    deleted: Mapped[bool] = mapped_column(default=False, server_default=text("false"))


def create_engine(settings: Settings) -> AsyncEngine | None:
    """Build the engine, or None when no DATABASE_URL is set.

    Nothing connects here: the pool opens connections on first use, so the app boots
    without a reachable database.
    """
    if settings.database_url is None:
        return None
    # pool_pre_ping replaces a connection the server dropped while idle instead of
    # failing the request that happens to pick it up. The session time zone is UTC because
    # `CURRENT_TIMESTAMP` fills a column without a time zone in the session's own zone, and
    # every timestamp here is UTC (ADR-0014).
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"timezone": "UTC"}},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: async code cannot lazy-load an expired attribute, so after a
    # commit the objects stay readable as they were.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request; closed (and an open transaction rolled back) when it ends.

    Nothing is committed here: the service that owns a use case calls commit() itself.
    """
    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "session_factory", None
    )
    if factory is None:
        # The message reaches the server log only; the client gets a plain 500 (the
        # error envelope is task 4.2).
        raise RuntimeError("DATABASE_URL is not set, so there is no database session")
    async with factory() as session:
        yield session
