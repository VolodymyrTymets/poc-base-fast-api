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
from pathlib import Path
from typing import Any

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

REPO_ROOT = Path(__file__).resolve().parents[2]
WAIT_SECONDS = 20


async def read_json_lines(
    process: asyncio.subprocess.Process, message: str
) -> dict[str, Any]:
    """The first JSON log line of the worker whose message is `message`; fails after WAIT_SECONDS."""
    assert process.stdout is not None
    seen: list[str] = []
    try:
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    pytest.fail(f"worker exited before logging {message!r}: {seen}")
                line = raw.decode().strip()
                seen.append(line)
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("message") == message:
                    return entry
    except TimeoutError:
        pytest.fail(f"no {message!r} line from the worker in {WAIT_SECONDS}s: {seen}")


async def test_a_job_enqueued_by_the_client_runs_in_the_worker_process(
    redis_settings: Settings,
) -> None:
    env = {
        **os.environ,
        "APP_ENV": "test",
        "REDIS_HOST": redis_settings.redis_host,
        "REDIS_PORT": str(redis_settings.redis_port),
        "REDIS_DATABASE": str(redis_settings.redis_database),
        "REDIS_PASSWORD": (
            redis_settings.redis_password.get_secret_value()
            if redis_settings.redis_password
            else ""
        ),
    }
    queue = ArqQueueClient(redis_settings)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "arq",
        "app.worker.WorkerSettings",
        cwd=REPO_ROOT,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        await read_json_lines(process, "worker startup")
        await queue.enqueue("ping")

        entry = await read_json_lines(process, "ping job ran")
    finally:
        await queue.close()
        if process.returncode is None:
            process.send_signal(signal.SIGTERM)
        await asyncio.wait_for(process.wait(), WAIT_SECONDS)

    assert (entry["logger"], entry["level"], entry["job_try"]) == (
        "app.workers.ping",
        "INFO",
        1,
    )


async def test_a_job_that_keeps_retrying_runs_three_times_with_growing_delays(
    redis_settings: Settings,
) -> None:
    base = 0.1
    started: list[float] = []

    async def flaky(ctx: dict[str, Any]) -> None:
        started.append(time.monotonic())
        raise Retry(defer=retry_delay(ctx["job_try"], base=base))

    queue = ArqQueueClient(redis_settings)
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
        await queue.enqueue("flaky")
        async with asyncio.timeout(WAIT_SECONDS):
            with pytest.raises(FailedJobs):
                await worker.run_check()
    finally:
        await queue.close()
        await worker.close()

    first_gap, second_gap = started[1] - started[0], started[2] - started[1]
    assert len(started) == 3
    assert (first_gap >= base, second_gap >= base * 2) == (True, True)
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
    redis_settings: Settings,
) -> None:
    app = create_app(redis_settings)

    @app.post("/enqueue-ping")
    async def enqueue_ping(
        queue: QueueClient = Depends(get_queue),  # noqa: B008
    ) -> dict[str, str]:
        await queue.enqueue("ping")
        return {"status": "queued"}

    pool: ArqRedis = await create_pool(
        arq_redis_settings(redis_settings),
        job_serializer=json_serializer,
        job_deserializer=json_deserializer,
    )
    try:
        async with running_client(app) as http_client:
            response: httpx.Response = await http_client.post("/enqueue-ping")
        queued = await pool.queued_jobs()
    finally:
        await pool.aclose()

    assert (response.status_code, response.json()) == (200, {"status": "queued"})
    assert [job.function for job in queued] == ["ping"]
