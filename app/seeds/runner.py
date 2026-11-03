"""Runs the seed items in order and records each in SeedHistory. Task: 5.1.

Ports the Node `MigrationsService` and `MigrationService`, with one deliberate difference (rule D5): the Node code stored
the error and carried on; here the runner stores it and raises `SeedError`, and the items after it do not run.
"""

import logging
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.db import create_engine, create_session_factory, new_id
from app.models import SeedHistory
from app.seeds.base import SeedError, SeedItem

logger = logging.getLogger(__name__)

# Held for the length of one item's transaction. Two processes starting together take turns, and the one that waits
# sees the first one's history row and skips. Arbitrary but fixed: every runner must use the same key.
SEED_LOCK_KEY = 5_100_001

# `result` holds an error message, not a log: a seed that fails on a huge value must not bloat the table.
MAX_RESULT_LENGTH = 2000


def describe(error: Exception) -> str:
    """Class and message of the error, for `SeedHistory.result`.

    A database error is described by the driver's own error: SQLAlchemy's wrapper adds the statement text, which
    is noise in a table column. (Its parameters are hidden by the engine, `hide_parameters` in app/core/db.py.)
    """
    cause = error.orig if isinstance(error, DBAPIError) and error.orig else error
    return f"{type(cause).__name__}: {cause}"[:MAX_RESULT_LENGTH]


async def record(
    session: AsyncSession, name: str, *, successful: bool, result: str | None
) -> None:
    """Insert the item's row, or update it when an earlier run left one (`name` is unique)."""
    insert_row = insert(SeedHistory).values(
        id=new_id(), name=name, successful=successful, result=result
    )
    await session.execute(
        insert_row.on_conflict_do_update(
            index_elements=[SeedHistory.name],
            set_={"successful": successful, "result": result},
        )
    )


async def run_item(
    session_factory: async_sessionmaker[AsyncSession], item: SeedItem
) -> bool:
    """Run one item in one transaction; True when it ran, False when it was skipped."""
    async with session_factory() as session, session.begin():
        await session.execute(select(func.pg_advisory_xact_lock(SEED_LOCK_KEY)))
        passed = await session.scalar(
            select(SeedHistory.id).where(
                SeedHistory.name == item.name, SeedHistory.successful.is_(True)
            )
        )
        if passed is not None or not await item.needs_to_run(session):
            return False
        await item.run(session)
        await record(session, item.name, successful=True, result=None)
        return True


async def record_failure(
    session_factory: async_sessionmaker[AsyncSession], name: str, error: Exception
) -> None:
    async with session_factory() as session, session.begin():
        await record(session, name, successful=False, result=describe(error))


async def run_seeds(
    session_factory: async_sessionmaker[AsyncSession], items: Sequence[SeedItem]
) -> None:
    """Run the items in order. A failing item is rolled back and recorded, then `SeedError` stops the run."""
    for item in items:
        try:
            ran = await run_item(session_factory, item)
        except Exception as error:
            # The item's own transaction is already rolled back. The failure is recorded in a new one;
            # if that fails too (the database is gone), the original error is still the one raised.
            try:
                await record_failure(session_factory, item.name, error)
            except Exception:
                logger.exception("seed %s: could not record the failure", item.name)
            logger.error("seed %s failed: %s", item.name, describe(error))
            raise SeedError(f"seed {item.name} failed: {describe(error)}") from error
        logger.info("seed %s: %s", item.name, "done" if ran else "nothing to do")


async def seed_database(settings: Settings, items: Sequence[SeedItem]) -> None:
    """`run_seeds` on a database of its own: for a command or a test helper that has no app engine to borrow."""
    engine = create_engine(settings)
    if engine is None:
        raise SeedError("DATABASE_URL is not set; the seeds need a database")
    try:
        await run_seeds(create_session_factory(engine), items)
    finally:
        await engine.dispose()
