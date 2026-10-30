"""Async engine, the request-scoped session dependency, the declarative Base and the column mixins. Tasks: 2.1."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_engine(settings: Settings) -> AsyncEngine | None:
    """Build the engine, or None when no DATABASE_URL is set.

    Nothing connects here: the pool opens connections on first use, so the app boots
    without a reachable database.
    """
    if settings.database_url is None:
        return None
    # pool_pre_ping replaces a connection the server dropped while idle instead of
    # failing the request that happens to pick it up.
    return create_async_engine(settings.database_url, pool_pre_ping=True)


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
