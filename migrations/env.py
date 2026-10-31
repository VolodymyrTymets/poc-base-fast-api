"""Alembic environment, async (asyncpg). The database URL comes from Settings, never from alembic.ini. Tasks: 2.4."""

import asyncio
import importlib
from logging.config import fileConfig

from alembic import context
from alembic.util import CommandError
from sqlalchemy.engine import Connection
from sqlalchemy.schema import SchemaItem

from app.config import get_settings
from app.core.db import Base, create_engine

# Importing the package is what registers the tables on Base.metadata, which `alembic check`
# compares with the database.
importlib.import_module("app.models")

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: the default would silence the loggers of the process
    # that calls alembic (a test run, for one).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

MISSING_URL = "DATABASE_URL is not set; migrations read the database URL from it (docs/RUNBOOK.md)"

# PostGIS creates this table in `public` with the extension. It is not ours, so it must not
# show up in `alembic check` as a table the models forgot; every other unknown table still does.
POSTGIS_TABLES = frozenset({"spatial_ref_sys"})


def include_object(
    obj: SchemaItem,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    is_postgis_table = (
        type_ == "table" and reflected and compare_to is None and name in POSTGIS_TABLES
    )
    return not is_postgis_table


def run_migrations_offline() -> None:
    """Render the SQL without connecting (`alembic upgrade head --sql`)."""
    url = get_settings().database_url
    if url is None:
        raise CommandError(MISSING_URL)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # The app's own engine factory, so migrations run in the same UTC session time zone the
    # app does (a `CURRENT_TIMESTAMP` default is filled in the session's zone).
    engine = create_engine(get_settings())
    if engine is None:
        raise CommandError(MISSING_URL)

    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    # asyncio.run: alembic's commands are synchronous. A caller already inside an event loop
    # (an async test) must run the command in a worker thread.
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
