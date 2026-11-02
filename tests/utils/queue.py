"""A queue that records the jobs an endpoint or service enqueues instead of sending them to Redis.

The real `QueueClient` protocol and the arq implementation come with task 6.1, which also adapts this fake to it. Until
then the shape is the smallest one that lets a test say "this call enqueued this job with these arguments".
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EnqueuedJob:
    name: str
    args: tuple[object, ...]
    kwargs: dict[str, object]


class FakeQueue:
    """In memory only: nothing here opens a connection."""

    def __init__(self) -> None:
        self._jobs: list[EnqueuedJob] = []

    async def enqueue(self, job_name: str, *args: object, **kwargs: object) -> None:
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
