"""Count the statements an engine runs, to prove that a cache hit reaches no database (task 9.2)."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine


@contextmanager
def count_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    """The SQL text of every statement the engine runs inside the block, in order."""
    statements: list[str] = []
    sync_engine: Engine = engine.sync_engine

    def record(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(sync_engine, "before_cursor_execute", record)
