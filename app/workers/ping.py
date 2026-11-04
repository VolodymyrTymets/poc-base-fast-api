"""A smoke job: it proves a job enqueued by the API runs in the worker process. Task: 6.1."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def ping(ctx: dict[str, Any]) -> None:
    # No arguments are logged: a job's arguments can hold personal data (rule P4), and the real jobs (6.2) do.
    logger.info("ping job ran", extra={"job_try": ctx["job_try"]})
