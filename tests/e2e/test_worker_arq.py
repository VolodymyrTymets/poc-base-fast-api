"""The arq worker and the queue client against a real Redis (task 6.1, ADR-0005).

Redis comes from `TEST_REDIS_URL` or a container (`redis_target`); the tests use database index 15 only.
"""

import asyncio
import json
import os
import signal
import socket
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any

import httpx
import pytest
from arq import Retry, create_pool
from arq.connections import ArqRedis
from arq.worker import FailedJobs, Worker, func
from fastapi import Depends
from redis.exceptions import RedisError
from utils.client import running_client

from app.config import Settings
from app.core.queue import (
    ArqQueueClient,
    QueueClient,
    json_deserializer,
    json_serializer,
    retry_delay,
)
from app.core.queue import redis_settings as arq_redis_settings
from app.dependencies import get_queue
from app.main import API_PREFIX, create_app

WAIT_SECONDS = 20

# Reads the next JSON log line of the worker with this message; fails with everything seen after WAIT_SECONDS.
LogReader = Callable[[str], Awaitable[dict[str, Any]]]


@pytest.fixture
async def arq_client(redis_settings: Settings) -> AsyncIterator[ArqQueueClient]:
    client = ArqQueueClient(redis_settings)
    yield client
    await client.close()


@pytest.fixture
async def arq_pool(redis_settings: Settings) -> AsyncIterator[ArqRedis]:
    """A raw arq pool, to look at what is in the queue."""
    pool: ArqRedis = await create_pool(
        arq_redis_settings(redis_settings),
        job_serializer=json_serializer,
        job_deserializer=json_deserializer,
    )
    yield pool
    await pool.aclose()


@pytest.fixture
async def worker_logs(redis_settings: Settings) -> AsyncIterator[LogReader]:
    """Starts `arq app.worker.WorkerSettings` as its own process and stops it with SIGTERM after the test."""
    env = {
        **os.environ,
        "APP_ENV": "test",
        # Pinned, so a developer's own LOG_LEVEL cannot hide the line a test waits for.
        "LOG_LEVEL": "INFO",
        "REDIS_HOST": redis_settings.redis_host,
        "REDIS_PORT": str(redis_settings.redis_port),
        "REDIS_DATABASE": str(redis_settings.redis_database),
        "REDIS_PASSWORD": (
            redis_settings.redis_password.get_secret_value()
            if redis_settings.redis_password
            else ""
        ),
    }
    # No cwd: the autouse fixture already runs the test from an empty directory, so no `.env` is read.
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "arq",
        "app.worker.WorkerSettings",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    seen: list[str] = []

    async def read(message: str) -> dict[str, Any]:
        assert process.stdout is not None
        try:
            async with asyncio.timeout(WAIT_SECONDS):
                while True:
                    raw = await process.stdout.readline()
                    if not raw:
                        pytest.fail(f"worker exited before {message!r}: {seen}")
                    line = raw.decode().strip()
                    seen.append(line)
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("message") == message:
                        return entry
        except TimeoutError:
            pytest.fail(f"no {message!r} from the worker in {WAIT_SECONDS}s: {seen}")

    yield read
    if process.returncode is None:
        process.send_signal(signal.SIGTERM)
    await asyncio.wait_for(process.wait(), WAIT_SECONDS)


async def test_a_job_enqueued_by_the_client_runs_in_the_worker_process(
    arq_client: ArqQueueClient, worker_logs: LogReader
) -> None:
    await worker_logs("worker startup")

    await arq_client.enqueue("ping")
    entry = await worker_logs("ping job ran")

    assert (entry["logger"], entry["level"], entry["job_try"]) == (
        "app.workers.ping",
        "INFO",
        1,
    )


async def test_the_password_reset_job_logs_the_recipient_and_token_in_the_test_environment(
    arq_client: ArqQueueClient, worker_logs: LogReader
) -> None:
    await worker_logs("worker startup")

    await arq_client.enqueue(
        "send_password_reset", "account-1", "reset.me@example.test", "fake-reset-value"
    )
    entry = await worker_logs(
        "[EMAIL] Password reset for reset.me@example.test (account account-1): token fake-reset-value"
    )

    assert (entry["logger"], entry["level"]) == ("app.workers.email", "INFO")


async def test_the_totp_job_logs_the_masked_phone_only(
    arq_client: ArqQueueClient, worker_logs: LogReader
) -> None:
    await worker_logs("worker startup")

    await arq_client.enqueue("send_totp_code", "+380000000001", "482913")
    entry = await worker_logs("[SMS] TOTP code sent to ***0001")

    assert (entry["logger"], entry["level"]) == ("app.workers.sms", "INFO")


async def test_a_job_that_keeps_retrying_runs_three_times_with_growing_delays(
    redis_settings: Settings, arq_client: ArqQueueClient
) -> None:
    base = 0.1
    started: list[float] = []

    async def flaky(ctx: dict[str, Any]) -> None:
        started.append(time.monotonic())
        raise Retry(defer=retry_delay(ctx["job_try"], base=base))

    worker = Worker(
        functions=[func(flaky, name="flaky")],
        redis_settings=arq_redis_settings(redis_settings),
        max_tries=3,
        keep_result=0,
        job_serializer=json_serializer,
        job_deserializer=json_deserializer,
        handle_signals=False,
        poll_delay=0.05,
        # Burst mode ends when the queue, deferred retries included, is empty: after the last failure.
        burst=True,
    )
    try:
        await arq_client.enqueue("flaky")
        async with asyncio.timeout(WAIT_SECONDS):
            with pytest.raises(FailedJobs):
                await worker.run_check()
    finally:
        await worker.close()

    assert len(started) == 3
    # Lower bounds only: the clock never runs the retry before its delay has passed.
    assert started[1] - started[0] >= base
    assert started[2] - started[1] >= base * 2
    assert worker.jobs_failed == 1


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


async def test_the_api_boots_without_redis_and_an_enqueue_then_fails() -> None:
    settings = Settings(redis_host="127.0.0.1", redis_port=unused_port())
    app = create_app(settings)

    async with running_client(app) as http_client:
        health = await http_client.get(f"{API_PREFIX}/health")
        with pytest.raises((OSError, RedisError)):
            await app.state.queue.enqueue("ping")

    assert (health.status_code, health.json()) == (200, {"status": "ok"})


async def test_a_route_enqueues_through_the_injected_queue(
    redis_settings: Settings, arq_pool: ArqRedis
) -> None:
    app = create_app(redis_settings)

    @app.post("/enqueue-ping")
    async def enqueue_ping(
        queue: Annotated[QueueClient, Depends(get_queue)],
    ) -> dict[str, str]:
        await queue.enqueue("ping")
        return {"status": "queued"}

    async with running_client(app) as http_client:
        response: httpx.Response = await http_client.post("/enqueue-ping")
    queued = await arq_pool.queued_jobs()

    assert (response.status_code, response.json()) == (200, {"status": "queued"})
    assert [job.function for job in queued] == ["ping"]
