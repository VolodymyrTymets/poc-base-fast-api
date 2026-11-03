"""`db_session`: what a test commits through it is undone when the test ends."""

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import utc_now
from app.models import Account


async def test_a_commit_through_db_session_is_not_visible_to_another_connection(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    db_session.add(Account(id="session-probe", last_login_at=utc_now()))
    await db_session.commit()

    async with db_engine.connect() as other:
        elsewhere = (
            await other.execute(
                text("SELECT count(*) FROM \"Account\" WHERE id = 'session-probe'")
            )
        ).scalar_one()
    here = (
        await db_session.execute(
            select(func.count())
            .select_from(Account)
            .where(Account.id == "session-probe")
        )
    ).scalar_one()

    assert (here, elsewhere) == (1, 0)


async def test_the_next_test_starts_without_what_the_previous_one_committed(
    db_session: AsyncSession,
) -> None:
    # Passes in any order; it fails only if the previous test's commit had leaked.
    leaked = (
        await db_session.execute(
            select(func.count())
            .select_from(Account)
            .where(Account.id == "session-probe")
        )
    ).scalar_one()

    assert leaked == 0
