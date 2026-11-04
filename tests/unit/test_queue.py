import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from arq.connections import RedisSettings
from pydantic import SecretStr
from utils.queue import FakeQueue

from app.config import Settings
from app.core.queue import (
    ArqQueueClient,
    QueueClient,
    json_deserializer,
    json_serializer,
    redis_settings,
    retry_delay,
)


class FakePool:
    """Stands in for ArqRedis, the one boundary mocked (testing-python rule 3)."""

    def __init__(self) -> None:
        self.enqueue_job = AsyncMock(return_value=object())
        self.aclose = AsyncMock()


def test_fake_queue_and_arq_client_both_satisfy_the_protocol() -> None:
    clients: list[QueueClient] = [FakeQueue(), ArqQueueClient(Settings())]

    assert len(clients) == 2


def test_retry_delay_doubles_on_every_try() -> None:
    assert [retry_delay(try_) for try_ in (1, 2, 3)] == [5, 10, 20]
    assert retry_delay(3, base=1) == 4


def test_retry_delay_rejects_a_try_below_one() -> None:
    with pytest.raises(ValueError, match="starts at 1"):
        retry_delay(0)


def test_the_serializer_round_trips_json_and_refuses_anything_else() -> None:
    payload: dict[str, Any] = {"t": None, "f": "ping", "a": ["x", 1], "k": {"n": 2}}

    assert json_deserializer(json_serializer(payload)) == payload
    with pytest.raises(TypeError):
        json_serializer({"a": {1, 2}})
    with pytest.raises(TypeError, match="JSON object"):
        json_deserializer(json.dumps([1]).encode())


def test_redis_settings_are_built_from_settings() -> None:
    settings = Settings(
        redis_host="r",
        redis_port=6380,
        redis_database=15,
        redis_password=SecretStr("pw"),
    )

    built = redis_settings(settings, conn_retries=0)

    assert isinstance(built, RedisSettings)
    assert (built.host, built.port, built.database, built.password) == (
        "r",
        6380,
        15,
        "pw",
    )
    assert built.conn_retries == 0


async def test_constructing_the_client_opens_no_connection() -> None:
    factory = AsyncMock()

    ArqQueueClient(Settings(), pool_factory=factory)

    factory.assert_not_called()


async def test_the_first_enqueue_opens_one_pool_and_sends_the_job() -> None:
    pool = FakePool()
    factory = AsyncMock(return_value=pool)
    client = ArqQueueClient(Settings(), pool_factory=factory)

    await client.enqueue("ping", "a", n=1)
    await client.enqueue("ping")

    factory.assert_awaited_once()
    assert factory.await_args is not None
    assert factory.await_args.args[0].conn_retries == 0
    assert factory.await_args.kwargs["job_serializer"] is json_serializer
    assert pool.enqueue_job.await_count == 2
    pool.enqueue_job.assert_any_await("ping", "a", n=1)


async def test_an_unreachable_redis_is_one_attempt_and_enqueue_raises() -> None:
    factory = AsyncMock(side_effect=ConnectionError("down"))
    client = ArqQueueClient(Settings(), pool_factory=factory)

    with pytest.raises(ConnectionError):
        await client.enqueue("ping")

    factory.assert_awaited_once()


async def test_a_kwarg_starting_with_an_underscore_is_refused() -> None:
    factory = AsyncMock(return_value=FakePool())
    client = ArqQueueClient(Settings(), pool_factory=factory)

    with pytest.raises(ValueError, match="_job_id"):
        await client.enqueue("ping", _job_id="x")

    factory.assert_not_called()


async def test_a_job_that_was_not_enqueued_raises() -> None:
    pool = FakePool()
    pool.enqueue_job.return_value = None
    client = ArqQueueClient(Settings(), pool_factory=AsyncMock(return_value=pool))

    with pytest.raises(RuntimeError, match="not enqueued"):
        await client.enqueue("ping")


async def test_close_closes_the_pool_once_and_is_safe_without_one() -> None:
    pool = FakePool()
    client = ArqQueueClient(Settings(), pool_factory=AsyncMock(return_value=pool))

    await client.close()
    await client.enqueue("ping")
    await client.close()
    await client.close()

    pool.aclose.assert_awaited_once()
