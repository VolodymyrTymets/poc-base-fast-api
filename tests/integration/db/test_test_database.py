"""The server and the template database the database tests run on (task 3.1)."""

import importlib

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from utils.db import REPO_ROOT, database_url_for

from app.core.db import Base


async def test_the_database_server_url_reaches_a_server_that_offers_postgis(
    database_url: str,
) -> None:
    # Offered, not installed: the first Alembic revision runs CREATE EXTENSION postgis in each database.
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            versions = (
                (
                    await connection.execute(
                        text(
                            "SELECT default_version FROM pg_available_extensions "
                            "WHERE name = 'postgis'"
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    assert database_url.startswith("postgresql+asyncpg://")
    assert [version[:2] for version in versions] == ["3."]


async def test_the_template_database_holds_the_model_tables_at_the_head_revision(
    database_url: str, template_database: str
) -> None:
    importlib.import_module("app.models")
    head = ScriptDirectory.from_config(
        Config(str(REPO_ROOT / "alembic.ini"))
    ).get_current_head()
    engine = create_async_engine(database_url_for(database_url, template_database))
    try:
        async with engine.connect() as connection:
            tables = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            revisions = (
                (
                    await connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    # alembic_version and spatial_ref_sys are put there by Alembic and PostGIS themselves.
    assert tables == {*Base.metadata.tables, "alembic_version", "spatial_ref_sys"}
    assert revisions == [head]
