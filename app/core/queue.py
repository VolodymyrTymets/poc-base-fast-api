"""The queue seam: a `QueueClient` protocol and its arq implementation. Task: 6.1 (ADR-0005).

It lives in `core` so that services (the notifier, task 6.3) and dependencies can take a `QueueClient` without importing
the worker layer. Callers depend on the protocol only: tests inject `FakeQueue` (tests/utils/queue.py), production uses
`ArqQueueClient`.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.exceptions import AuthenticationError, AuthorizationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config import Settings

# Between two tries of a job: BACKOFF_BASE_SECONDS, then twice that, then four times (ADR-0005: arq has no backoff setting).
BACKOFF_BASE_SECONDS = 5.0
# Matches the scope doc and ADR-0005: three tries, then the job fails for good.
MAX_TRIES = 3


# What "Redis is down" looks like. Any other RedisError (ResponseError, DataError, ...) is a bad ACL, a full server or a bug:
# it must reach the caller as itself and never pass for an outage (rule D5). asyncio's timeout is a builtin TimeoutError,
# an OSError, which is what arq's `create_pool` raises when the server does not answer.
_UNAVAILABLE = (RedisConnectionError, RedisTimeoutError, OSError)


class QueueUnavailableError(RuntimeError):
    """The queue could not be reached (task 6.3, ADR-0027). The original error is the `__cause__`.

    The one queue failure a notifier may log and go on from. It carries no job arguments, which can hold a code or a token.
    """


class QueueClient(Protocol):
    """What a notifier needs from a queue: hand a named job its arguments, and nothing else."""

    async def enqueue(self, job_name: str, *args: object, **kwargs: object) -> None: ...


def retry_delay(job_try: int, base: float = BACKOFF_BASE_SECONDS) -> float:
    """Seconds to wait before try `job_try + 1`; `job_try` is arq's `ctx["job_try"]`, which starts at 1."""
    if job_try < 1:
        raise ValueError("job_try starts at 1")
    return base * float(2 ** (job_try - 1))


def _json_default(value: object) -> str:
    # arq serializes the failure of a job that ran out of tries (a JobExecutionFailed) even when results are not kept;
    # its text is all that is wanted. Any other non-JSON value stays an error, so a bad job argument still raises.
    if isinstance(value, BaseException):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def json_serializer(data: dict[str, Any]) -> bytes:
    # Not pickle (AC7): whoever can write to Redis could otherwise run code in the worker.
    return json.dumps(data, default=_json_default).encode()


def json_deserializer(raw: bytes) -> dict[str, Any]:
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise TypeError("a job payload must be a JSON object")
    return decoded


def redis_settings(settings: Settings, *, conn_retries: int = 5) -> RedisSettings:
    """Connection settings for arq, from our `Settings`. arq's own default is five connection retries."""
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        database=settings.redis_database,
        password=(
            settings.redis_password.get_secret_value()
            if settings.redis_password
            else None
        ),
        conn_retries=conn_retries,
    )


class ArqQueueClient:
    """Enqueues onto arq. The Redis pool opens on the first `enqueue`, so the app boots with no Redis (AC4)."""

    def __init__(
        self,
        settings: Settings,
        *,
        pool_factory: Callable[..., Awaitable[ArqRedis]] = create_pool,
    ) -> None:
        # conn_retries=0 is one attempt: a request fails at once when Redis is down instead of hanging for arq's
        # five retries a second apart.
        self._redis_settings = redis_settings(settings, conn_retries=0)
        self._pool_factory = pool_factory
        self._pool: ArqRedis | None = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> ArqRedis:
        async with self._lock:
            if self._pool is None:
                self._pool = await self._pool_factory(
                    self._redis_settings,
                    job_serializer=json_serializer,
                    job_deserializer=json_deserializer,
                )
            return self._pool

    async def enqueue(self, job_name: str, *args: object, **kwargs: object) -> None:
        # arq reads `_job_id`, `_defer_by` and the like from the kwargs; this client exposes none of them yet, and a job
        # argument must never be mistaken for one.
        reserved = sorted(key for key in kwargs if key.startswith("_"))
        if reserved:
            raise ValueError(
                f"job arguments cannot start with an underscore: {reserved}"
            )
        # Widened to Any because arq types its own `_`-prefixed options, which the check above keeps out of kwargs.
        job_kwargs: dict[str, Any] = dict(kwargs)
        try:
            pool = await self._get_pool()
            job = await pool.enqueue_job(job_name, *args, **job_kwargs)
        except AuthenticationError, AuthorizationError:
            # Subclasses of redis's ConnectionError, but a wrong or missing REDIS_PASSWORD is a configuration fault: it must
            # reach the caller as itself, or every job would be dropped behind a log line that reads like an outage (rule D5).
            raise
        except _UNAVAILABLE as error:
            # An unreachable Redis raises (rule D5); there is no silent drop. The text names no argument.
            raise QueueUnavailableError(f"cannot enqueue {job_name}") from error
        if job is None:
            # Only possible with a `_job_id` that already exists, which this client never sets.
            raise RuntimeError(f"job {job_name} was not enqueued")

    async def close(self) -> None:
        async with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            await pool.aclose()
