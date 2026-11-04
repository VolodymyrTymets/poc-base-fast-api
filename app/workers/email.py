"""The email job: log only, no provider is wired. Task: 6.2, ADR-0026."""

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# Where the flow may be finished by hand from the worker log (ADR-0026).
LOG_MESSAGE_ENVIRONMENTS = frozenset({"local", "development", "test"})


async def send_password_reset(
    ctx: dict[str, Any], account_id: str, email: str, token: str
) -> None:
    """Idempotent: no state and no external call, so a retry only logs the same line again."""
    if get_settings().app_env in LOG_MESSAGE_ENVIRONMENTS:
        # WHY: ADR-0026, POC-6.2. No `=` or `:` after "token": the format `redact` leaves alone.
        logger.info(
            "[EMAIL] Password reset for %s (account %s): token %s",
            email,
            account_id,
            token,
        )
        return
    logger.info(
        "[EMAIL] Password reset email queued for account %s; no email provider is configured",
        account_id,
    )
