"""Waits until Postgres accepts a connection; the container entrypoint runs it before it migrates. Task: POC-11.1.

Reads `DATABASE_URL` (the same `postgresql+asyncpg://` value the app uses), then makes exactly `DB_WAIT_ATTEMPTS` connection
attempts (default 30), `DB_WAIT_INTERVAL_SECONDS` apart (default 1). The Node entrypoint announced 30 attempts and made 5
(issue I.6), so the count printed here is the count of attempts made.

Exit status: 0 reachable, 1 gave up, 2 a bad or missing setting. It prints the exception class of a failed attempt and never the
URL or the password (rule D8), and it imports nothing from `app`: it must run before the app's settings and schema are usable.
"""

import asyncio
import logging
import os
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

DEFAULT_ATTEMPTS = 30
DEFAULT_INTERVAL_SECONDS = 1.0
CONNECT_TIMEOUT_SECONDS = 5.0
# The only URL the app accepts (RUNBOOK, "First run"); anything else is a setting error, not a database that is not up yet.
DRIVER = "postgresql+asyncpg"

logger = logging.getLogger("wait_for_postgres")


def read_settings() -> tuple[str, int, float]:
    """The database URL, the attempt count and the pause between attempts; raises ValueError naming the variable."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("DATABASE_URL is not set")
    try:
        driver = make_url(url).drivername
    except ArgumentError:
        # Not a URL at all; the check below reports it without the text.
        driver = ""
    if driver != DRIVER:
        # Never `str(error)`: SQLAlchemy's message for a bad URL contains the whole URL, password included (rule D8).
        raise ValueError(f"DATABASE_URL must be a {DRIVER}:// URL")
    raw_attempts = os.environ.get("DB_WAIT_ATTEMPTS", str(DEFAULT_ATTEMPTS))
    try:
        attempts = int(raw_attempts)
    except ValueError:
        attempts = 0
    if attempts < 1:
        raise ValueError("DB_WAIT_ATTEMPTS must be a whole number of at least 1")
    raw_interval = os.environ.get(
        "DB_WAIT_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)
    )
    try:
        interval = float(raw_interval)
    except ValueError:
        interval = -1.0
    if interval < 0:
        raise ValueError("DB_WAIT_INTERVAL_SECONDS must be a number of at least 0")
    return url, attempts, interval


async def try_connect(url: str) -> None:
    # The app's own connector (SQLAlchemy over asyncpg), so a URL the app accepts is one the wait accepts.
    engine = create_async_engine(url, connect_args={"timeout": CONNECT_TIMEOUT_SECONDS})
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def wait(url: str, attempts: int, interval: float) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            await try_connect(url)
        except (OSError, SQLAlchemyError, TimeoutError) as error:
            # The class only: the message can carry the host, the user or part of the URL.
            logger.warning(
                "attempt %d/%d failed: %s", attempt, attempts, type(error).__name__
            )
            if attempt < attempts:
                await asyncio.sleep(interval)
        else:
            logger.info("Postgres is reachable (attempt %d/%d)", attempt, attempts)
            return True
    return False


def main() -> int:
    # Plain messages on stdout, so the entrypoint's log shows them as written.
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    try:
        url, attempts, interval = read_settings()
    except ValueError as error:
        logger.error("wait_for_postgres: %s", error)
        return 2
    if asyncio.run(wait(url, attempts, interval)):
        return 0
    logger.error("Postgres not reachable after %d attempts", attempts)
    return 1


if __name__ == "__main__":
    sys.exit(main())
