"""The seed runner on a real, migrated and unseeded database. Task: 5.1.

Each test has its own database (`unseeded_session_factory`): the runner commits through its own sessions, and no test deletes
rows to start clean (rule P6). The items are fakes that write a `DeletedHistory` row, so the effect of a run, and of a
rollback, can be read back.
"""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import DeletedHistory, SeedHistory
from app.seeds.base import SeedError
from app.seeds.runner import run_seeds

type Factory = async_sessionmaker[AsyncSession]


class FakeItem:
    """Writes one row when it runs. `fail` is raised after the write, so a rollback has something to undo."""

    def __init__(
        self,
        name: str,
        *,
        needed: bool = True,
        fail: Exception | None = None,
        log: list[str] | None = None,
    ) -> None:
        self.name = name
        self.log = log
        self.needed = needed
        self.fail = fail
        self.runs = 0

    async def needs_to_run(self, session: AsyncSession) -> bool:
        return self.needed

    async def run(self, session: AsyncSession) -> None:
        self.runs += 1
        if self.log is not None:
            self.log.append(self.name)
        session.add(DeletedHistory(relation_id=self.name, deleted_at=False))
        await session.flush()
        if self.fail is not None:
            raise self.fail


class BadSqlItem(FakeItem):
    """Fails in the database with a value that must not reach `SeedHistory.result`."""

    async def run(self, session: AsyncSession) -> None:
        await session.execute(
            text(
                'INSERT INTO "AccountOnRole" ("roleId", "accountId") VALUES (:role, :account)'
            ),
            {"role": "param-value-1", "account": "param-value-2"},
        )


async def history(factory: Factory) -> dict[str, tuple[bool, str | None]]:
    async with factory() as session:
        rows = await session.scalars(select(SeedHistory))
        return {row.name: (row.successful, row.result) for row in rows}


async def written(factory: Factory) -> list[str]:
    async with factory() as session:
        rows = await session.scalars(
            select(DeletedHistory.relation_id).order_by(DeletedHistory.relation_id)
        )
        return list(rows)


async def test_an_item_runs_once_and_a_second_run_skips_it(
    unseeded_session_factory: Factory,
) -> None:
    item = FakeItem("first")

    await run_seeds(unseeded_session_factory, [item])
    await run_seeds(unseeded_session_factory, [item])

    assert item.runs == 1
    assert await written(unseeded_session_factory) == ["first"]
    assert await history(unseeded_session_factory) == {"first": (True, None)}


async def test_an_item_that_does_not_need_to_run_is_skipped_without_a_history_row(
    unseeded_session_factory: Factory,
) -> None:
    item = FakeItem("not-needed", needed=False)

    await run_seeds(unseeded_session_factory, [item])

    assert item.runs == 0
    assert await history(unseeded_session_factory) == {}


async def test_items_run_in_the_given_order(
    unseeded_session_factory: Factory,
) -> None:
    order: list[str] = []
    items = [FakeItem("b", log=order), FakeItem("a", log=order)]

    await run_seeds(unseeded_session_factory, items)

    assert order == ["b", "a"]


async def test_a_failing_item_is_rolled_back_recorded_and_raised(
    unseeded_session_factory: Factory,
) -> None:
    failing = FakeItem("broken", fail=ValueError("bad seed data"))
    after = FakeItem("after")

    with pytest.raises(SeedError, match="broken") as raised:
        await run_seeds(unseeded_session_factory, [failing, after])

    assert isinstance(raised.value.__cause__, ValueError)
    assert await written(unseeded_session_factory) == []
    assert await history(unseeded_session_factory) == {
        "broken": (False, "ValueError: bad seed data")
    }
    assert after.runs == 0


async def test_an_item_that_failed_earlier_succeeds_on_the_next_run_in_the_same_row(
    unseeded_session_factory: Factory,
) -> None:
    with pytest.raises(SeedError):
        await run_seeds(
            unseeded_session_factory, [FakeItem("retry", fail=RuntimeError("once"))]
        )

    await run_seeds(unseeded_session_factory, [FakeItem("retry")])

    assert await history(unseeded_session_factory) == {"retry": (True, None)}
    assert await written(unseeded_session_factory) == ["retry"]


async def test_the_recorded_error_of_a_database_failure_holds_no_sql_parameters(
    unseeded_session_factory: Factory,
) -> None:
    with pytest.raises(SeedError):
        await run_seeds(unseeded_session_factory, [BadSqlItem("bad-sql")])

    successful, result = (await history(unseeded_session_factory))["bad-sql"]
    assert successful is False
    assert result is not None
    assert "ForeignKeyViolationError" in result
    assert "param-value" not in result
    assert "[SQL:" not in result


async def test_two_runners_at_once_run_the_item_once(
    unseeded_session_factory: Factory,
) -> None:
    item = FakeItem("shared")

    await asyncio.gather(
        run_seeds(unseeded_session_factory, [item]),
        run_seeds(unseeded_session_factory, [item]),
    )

    assert item.runs == 1
    assert await written(unseeded_session_factory) == ["shared"]
    assert await history(unseeded_session_factory) == {"shared": (True, None)}
