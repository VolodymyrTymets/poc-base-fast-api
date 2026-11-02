"""The `frozen_clock` fixture (task 3.2): the process clock stops and moves only when the test says so."""

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from time_machine import TimeMachineFixture
from utils.clock import FROZEN_NOW

from app.core.db import utc_now

# utc_now() is naive on purpose (app/core/db.py): the columns are `timestamp without time zone`.
FROZEN_NAIVE = FROZEN_NOW.replace(tzinfo=None)


def test_the_clock_stands_still_at_the_frozen_instant(
    frozen_clock: TimeMachineFixture,
) -> None:
    first = datetime.now(UTC)
    second = datetime.now(UTC)

    assert (first, second) == (FROZEN_NOW, FROZEN_NOW)


def test_utc_now_is_the_frozen_instant_without_a_time_zone(
    frozen_clock: TimeMachineFixture,
) -> None:
    assert utc_now() == FROZEN_NAIVE


def test_shifting_moves_both_clocks_by_exactly_that_much(
    frozen_clock: TimeMachineFixture,
) -> None:
    frozen_clock.shift(timedelta(minutes=15, seconds=30))

    assert (datetime.now(UTC), utc_now()) == (
        FROZEN_NOW + timedelta(minutes=15, seconds=30),
        FROZEN_NAIVE + timedelta(minutes=15, seconds=30),
    )


async def test_app_code_behind_the_http_client_sees_the_frozen_clock(
    asgi_app: FastAPI, client: httpx.AsyncClient, frozen_clock: TimeMachineFixture
) -> None:
    @asgi_app.get("/api/v1/_now")
    async def now() -> dict[str, str]:
        return {"now": utc_now().isoformat()}

    before = await client.get("/api/v1/_now")
    frozen_clock.shift(timedelta(hours=1))
    after = await client.get("/api/v1/_now")

    assert (before.json(), after.json()) == (
        {"now": "2026-01-01T12:00:00"},
        {"now": "2026-01-01T13:00:00"},
    )


async def test_a_database_round_trip_works_under_the_frozen_clock(
    db_session: AsyncSession, frozen_clock: TimeMachineFixture
) -> None:
    # The risk this guards: a patched clock confusing asyncpg or the pool. Real database, frozen process clock.
    value = (await db_session.execute(text("SELECT 1"))).scalar_one()

    assert value == 1
