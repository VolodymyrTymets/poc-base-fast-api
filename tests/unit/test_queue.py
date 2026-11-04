import json
from typing import Any
from unittest.mock import create_autospec

import pytest
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import DataError, ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError
from utils.queue import FakeQueue

from app.config import Settings
from app.core.queue import (
    ArqQueueClient,
    QueueClient,
    QueueUnavailableError,
    json_deserializer,
    json_serializer,
    redis_settings,
    retry_delay,
)


def new_pool(*, job_enqueued: bool = True) -> Any:
    """An ArqRedis with the real method signatures (autospec), the one boundary mocked (testing-python rules 11, 13).

    Typed `Any` so a test can read the mock's assertions; `enqueue_job` answers None when `job_enqueued` is False.
    """
    pool = create_autospec(ArqRedis, instance=True)
    pool.enqueue_job.return_value = object() if job_enqueued else None
    return pool


def new_factory(pool: Any = None, error: Exception | None = None) -> Any:
    """A stand-in for `create_pool` with its real signature: a wrong keyword fails the test."""
    return create_autospec(
        create_pool, return_value=pool, side_effect=error if error else None
    )


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
    assert json.loads(
        json_serializer({"r": RuntimeError("max 3 retries exceeded")})
    ) == {"r": "max 3 retries exceeded"}
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
    factory = new_factory()

    ArqQueueClient(Settings(), pool_factory=factory)

    factory.assert_not_called()


async def test_the_first_enqueue_opens_one_pool_and_sends_the_job() -> None:
    pool = new_pool()
    factory = new_factory(pool)
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
    factory = new_factory(error=ConnectionError("down"))
    client = ArqQueueClient(Settings(), pool_factory=factory)

    with pytest.raises(QueueUnavailableError, match="cannot enqueue ping") as raised:
        await client.enqueue("ping")

    assert isinstance(raised.value.__cause__, ConnectionError)
    factory.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [RedisConnectionError("down"), RedisTimeoutError("slow"), TimeoutError()],
    ids=["redis-connection", "redis-timeout", "builtin-timeout"],
)
async def test_a_failing_enqueue_job_that_means_redis_is_down_is_wrapped(
    error: Exception,
) -> None:
    pool = new_pool()
    pool.enqueue_job.side_effect = error
    client = ArqQueueClient(Settings(), pool_factory=new_factory(pool))

    with pytest.raises(QueueUnavailableError) as raised:
        await client.enqueue("ping", "a-secret-argument")

    assert raised.value.__cause__ is error
    assert "a-secret-argument" not in str(raised.value)


@pytest.mark.parametrize(
    "error",
    [ResponseError("NOPERM"), DataError("bad"), ValueError("bug")],
    ids=["response-error", "data-error", "value-error"],
)
async def test_any_other_error_from_enqueue_job_propagates_unchanged(
    error: Exception,
) -> None:
    pool = new_pool()
    pool.enqueue_job.side_effect = error
    client = ArqQueueClient(Settings(), pool_factory=new_factory(pool))

    with pytest.raises(type(error)) as raised:
        await client.enqueue("ping")

    assert raised.value is error


async def test_a_kwarg_starting_with_an_underscore_is_refused() -> None:
    factory = new_factory(new_pool())
    client = ArqQueueClient(Settings(), pool_factory=factory)

    with pytest.raises(ValueError, match="_job_id"):
        await client.enqueue("ping", _job_id="x")

    factory.assert_not_called()


async def test_a_job_that_was_not_enqueued_raises() -> None:
    pool = new_pool(job_enqueued=False)
    client = ArqQueueClient(Settings(), pool_factory=new_factory(pool))

    with pytest.raises(RuntimeError, match="not enqueued"):
        await client.enqueue("ping")


async def test_close_closes_the_pool_once_and_is_safe_without_one() -> None:
    pool = new_pool()
    client = ArqQueueClient(Settings(), pool_factory=new_factory(pool))

    await client.close()
    await client.enqueue("ping")
    await client.close()
    await client.close()

    pool.aclose.assert_awaited_once()
