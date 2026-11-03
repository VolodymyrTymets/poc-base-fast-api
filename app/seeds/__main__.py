"""`python -m app.seeds`: run the seed items once and exit. Task: 5.1.

The same runner the app calls at startup, for a deploy step or a developer who wants the data without starting the server.
Exit status: 0 when every item ran or had nothing to do, 1 when there is no database or an item failed.
"""

import asyncio
import logging
import sys

from app.config import get_settings
from app.core.logging import configure_logging
from app.seeds.base import SeedError
from app.seeds.registry import seed_items
from app.seeds.runner import seed_database

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.database_url is None:
        sys.stderr.write("DATABASE_URL is not set; the seeds need a database\n")
        return 1
    try:
        asyncio.run(seed_database(settings, seed_items(settings)))
    except SeedError as error:
        # run_seeds already logged the item and recorded the failure; this is the exit status.
        sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
