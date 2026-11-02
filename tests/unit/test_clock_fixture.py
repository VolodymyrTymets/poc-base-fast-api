"""The `frozen_clock` fixture (task 3.2), process clock only: no database, app or HTTP is involved."""

from datetime import UTC, datetime, timedelta

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
