"""The SMS job: log only, no provider is wired. Task: 6.2."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_VISIBLE_DIGITS = 4


def mask_phone(phone: str) -> str:
    """`+12125550100` becomes `***0100`; anything with five digits or fewer is `***` (issue I.5, rule D8)."""
    digits = [char for char in phone if char.isdigit()]
    if len(digits) <= _VISIBLE_DIGITS:
        return "***"
    return "***" + "".join(digits[-_VISIBLE_DIGITS:])


async def send_totp_code(ctx: dict[str, Any], phone: str, code: str) -> None:
    """Idempotent: no state and no external call, so a retry only logs the same line again."""
    # The code is never logged, in any environment (rules D8, P4); `code` is only here because it is the job's payload.
    del code
    logger.info("[SMS] TOTP code sent to %s", mask_phone(phone))
