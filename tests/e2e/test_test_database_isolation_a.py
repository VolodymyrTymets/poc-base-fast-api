"""Module A of the pair that proves a test module gets a database of its own (see ..._b.py).

Each module commits one Account with its own id and then lists every Account it can see. If the two modules
shared a database, whichever ran second would see both ids, in either order.
"""

from sqlalchemy.ext.asyncio import AsyncEngine
from utils.db import commit_marker_account


async def test_module_a_sees_only_its_own_committed_account(
    db_engine: AsyncEngine,
) -> None:
    visible = await commit_marker_account(db_engine, "isolation-module-a")

    assert visible == ["isolation-module-a"]
