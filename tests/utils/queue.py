"""A queue that records the jobs an endpoint or service enqueues instead of sending them to Redis.

It satisfies the `QueueClient` protocol of `app.core.queue` (task 6.1), whose real implementation is `ArqQueueClient`. The
shape is the smallest one that lets a test say "this call enqueued this job with these arguments".
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.core.queue import QueueUnavailableError


@dataclass(frozen=True)
class EnqueuedJob:
    name: str
    args: tuple[object, ...]
    kwargs: dict[str, object]


class FakeQueue:
    """In memory only: nothing here opens a connection."""

    def __init__(self, fail_on: Iterable[str] = ()) -> None:
        self._jobs: list[EnqueuedJob] = []
        # Job names whose enqueue fails as an unreachable Redis does (`QueueUnavailableError`); nothing is recorded for them.
        self._fail_on = frozenset(fail_on)

    async def enqueue(self, job_name: str, *args: object, **kwargs: object) -> None:
        if job_name in self._fail_on:
            raise QueueUnavailableError(f"cannot enqueue {job_name}")
        # kwargs is copied so a caller that reuses its own dict cannot change what was recorded.
        self._jobs.append(EnqueuedJob(job_name, args, dict(kwargs)))

    @property
    def jobs(self) -> list[EnqueuedJob]:
        """Every job so far, in the order it was enqueued (a copy)."""
        return list(self._jobs)

    def named(self, job_name: str) -> list[EnqueuedJob]:
        return [job for job in self._jobs if job.name == job_name]

    def clear(self) -> None:
        self._jobs.clear()
