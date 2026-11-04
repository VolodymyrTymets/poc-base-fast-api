"""Helpers for the race tests: wait until a second transaction is blocked on a row lock held by the first. Tasks: 7.4, 7.5."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def lock_waiters(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        count = await connection.scalar(
            text(
                "select count(*) from pg_stat_activity "
                "where wait_event_type = 'Lock' and datname = current_database()"
            )
        )
    assert count is not None
    return int(count)


async def wait_for_a_lock_waiter(engine: AsyncEngine) -> None:
    # Polls a condition with a bound (about 10 s), not a guess at how long the other transaction needs.
    for _ in range(500):
        if await lock_waiters(engine) > 0:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("no transaction waited on a row lock within 10 seconds")
