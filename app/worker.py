"""The arq worker entrypoint: `uv run arq app.worker.WorkerSettings` (ADR-0005, ADR-0024). Task: 6.1.

arq imports this module by name, so the class has to be reachable as `app.worker.WorkerSettings`. Nothing in `app/`
imports it, and nothing here opens a connection at import: arq connects when it starts the worker.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from app.config import get_settings
from app.core.logging import configure_logging
from app.core.queue import (
    MAX_TRIES,
    json_deserializer,
    json_serializer,
    redis_settings,
)
from app.workers.email import send_password_reset
from app.workers.ping import ping
from app.workers.sms import send_totp_code

# arq's CLI calls dictConfig before `on_startup`, which gives the `arq` logger its own plain-text handler.
_ARQ_LOGGERS = ("arq", "arq.worker", "arq.jobs", "arq.connections")


class HideJobArguments(logging.Filter):
    """Replaces the argument text of arq's `→ ref(args)` line (rule P4).

    arq logs every job's positional and keyword arguments with `repr`. The redaction patterns catch phone numbers, JWTs and
    `key=value` pairs, but not a bare OTP code or reset token passed as a positional argument (tasks 6.2, 7.x), so the arguments
    are dropped from the log altogether; the job id and name stay.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # arq's format is '%6.2fs → %s(%s)%s': seconds, ref, arguments, extra.
        if (
            isinstance(record.msg, str)
            and "→" in record.msg
            and isinstance(record.args, tuple)
            and len(record.args) == 4
        ):
            seconds, ref, _arguments, extra = record.args
            record.args = (seconds, ref, "arguments hidden", extra)
        return True


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)
    logging.getLogger("arq.worker").addFilter(HideJobArguments())
    # Dropping arq's handler lets its records reach the root one: one JSON format, redacted, on stdout (AC8, rule P4).
    for name in _ARQ_LOGGERS:
        arq_logger = logging.getLogger(name)
        arq_logger.handlers = []
        arq_logger.propagate = True
    logging.getLogger(__name__).info("worker startup")


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Awaitable[None]]]] = [
        ping,
        send_totp_code,
        send_password_reset,
    ]
    # Retries are ours: a job raises `Retry(defer=retry_delay(ctx["job_try"]))`, arq stops after `max_tries`.
    max_tries = MAX_TRIES
    # Nothing reads a job's result, so none is stored (scope doc 6.1).
    keep_result = 0
    # arq also logs `repr(result)` of a finished job; a result can hold what an argument held (rule P4).
    log_results = False
    redis_settings = redis_settings(get_settings())
    job_serializer = staticmethod(json_serializer)
    job_deserializer = staticmethod(json_deserializer)
    on_startup = staticmethod(on_startup)
