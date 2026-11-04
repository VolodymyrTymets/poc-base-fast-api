"""NotifierService fan-out to SMS, log and email. Task: 6.3, ADR-0027.

Built from the profile service and a queue, not from a session, and it never commits: it writes nothing to the
database (ADR-0021 still holds for whoever owns the transaction). A database error while reading the profile
propagates: it says nothing about whether an email exists, and swallowing it would leave the caller's transaction
aborted without telling it. The one failure a channel absorbs is `QueueUnavailableError` (Redis down), logged with the
account id, so that a caller answers the same whether or not the account exists (no enumeration). Every other error from
the queue is a bug and propagates (rule D5).

Nothing here logs a code, a token, an email or a phone number (rules D8, P4); the worker jobs of task 6.2 decide what
their own log may show (ADR-0026).
"""

import logging
from collections.abc import Collection
from enum import StrEnum

from app.core.queue import QueueClient, QueueUnavailableError
from app.services.account_profile import AccountProfileService

logger = logging.getLogger(__name__)

# Job names and argument order are the contract with app/workers (task 6.2).
OTP_JOB = "send_totp_code"
RESET_JOB = "send_password_reset"


class NotifierType(StrEnum):
    SMS = "SMS"
    LOG = "LOG"
    EMAIL = "EMAIL"
    ALL = "ALL"


def _channels(types: Collection[NotifierType]) -> frozenset[NotifierType]:
    """The concrete channels asked for: `ALL` expands to the three, a repeated channel counts once."""
    if NotifierType.ALL in types:
        return frozenset({NotifierType.SMS, NotifierType.LOG, NotifierType.EMAIL})
    return frozenset(types)


class NotifierService:
    def __init__(self, profiles: AccountProfileService, queue: QueueClient) -> None:
        self._profiles = profiles
        self._queue = queue

    async def notify_about_totp_code(
        self, account_id: str, code: str, types: Collection[NotifierType]
    ) -> None:
        """Hands the sign-in code to the selected channels: the SMS job when the profile has a phone number."""
        channels = _channels(types)
        if not channels:
            return
        profile = await self._profiles.get_by_account_id(account_id)
        if NotifierType.SMS in channels and profile and profile.phone_number:
            await self._enqueue(account_id, OTP_JOB, profile.phone_number, code)
        if NotifierType.LOG in channels:
            # Node logged the code itself in `local` (rules D8, P4); here only the fact is logged.
            logger.info("sign-in code issued for account %s", account_id)

    async def notify_about_password_reset(
        self, account_id: str, token: str, types: Collection[NotifierType]
    ) -> None:
        """Hands the reset token to the selected channels: the email job when the profile has an email."""
        channels = _channels(types)
        if not channels:
            return
        profile = await self._profiles.get_by_account_id(account_id)
        if NotifierType.LOG in channels:
            logger.info("password reset issued for account %s", account_id)
        email = profile.email if profile else None
        if NotifierType.EMAIL in channels and email:
            await self._enqueue(account_id, RESET_JOB, account_id, email, token)

    async def _enqueue(self, account_id: str, job_name: str, *args: object) -> None:
        try:
            await self._queue.enqueue(job_name, *args)
        except QueueUnavailableError:
            # Logged, not raised: a throw would tell the client which accounts exist. The traceback names the job, never an argument.
            logger.exception("could not queue %s for account %s", job_name, account_id)
