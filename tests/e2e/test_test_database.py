"""The server the database tests run on (task 3.1): reachable, and PostGIS-enabled."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


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
