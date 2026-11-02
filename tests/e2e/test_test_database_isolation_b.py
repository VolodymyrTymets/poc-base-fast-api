"""Module B of the pair that proves a test module gets a database of its own (see ..._a.py)."""

from sqlalchemy.ext.asyncio import AsyncEngine
from utils.db import commit_marker_account


async def test_module_b_sees_only_its_own_committed_account(
    db_engine: AsyncEngine,
) -> None:
    visible = await commit_marker_account(db_engine, "isolation-module-b")

    assert visible == ["isolation-module-b"]
