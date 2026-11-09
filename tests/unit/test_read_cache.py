"""ReadCache: read-through, fail open, invalidation by SCAN (task 9.2, ADR-0035). Uses a small in-memory store, not Redis."""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from fnmatch import fnmatchcase

import pytest
from redis.exceptions import AuthenticationError, ResponseError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.cache import (
    CACHE_TTL_SECONDS,
    DELETE_BATCH_SIZE,
    Cache,
    NullReadCache,
    ReadCache,
    cache_key,
    serialize,
)

MODEL = "Account"
ARGS = {"accountId": "a1"}
AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class MemoryStore:
    """An in-memory `CacheStore`. `keys` is deliberately absent: a call to it is an AttributeError, so KEYS cannot slip in."""

    def __init__(
        self, fail_with: Exception | None = None, fail_on: str | None = None
    ) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail_with = fail_with
        self.fail_on = (
            fail_on  # None: every call fails; else only the call of that name
        )
        self.calls: list[str] = []
        self.delete_batches: list[int] = []

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_with is not None and self.fail_on in (None, name):
            raise self.fail_with

    async def get(self, key: str) -> str | None:
        self._check("get")
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self._check("set")
        self.data[key] = value
        self.ttls[key] = ex

    async def scan_iter(self, match: str) -> AsyncIterator[str]:
        self._check("scan_iter")
        # Redis writes a literal star as `\*`, fnmatch as `[*]`.
        glob = match.replace("\\*", "[*]")
        for key in list(self.data):
            if fnmatchcase(key, glob):
                yield key

    async def delete(self, *keys: str) -> int:
        self._check("delete")
        self.delete_batches.append(len(keys))
        for key in keys:
            self.data.pop(key, None)
        return len(keys)

    async def close(self) -> None:
        self.calls.append("close")


class Loader:
    def __init__(self, value: object) -> None:
        self.value = value
        self.count = 0

    async def __call__(self) -> object:
        self.count += 1
        return self.value


def encode(value: object) -> object:
    return value


def decode(raw: object) -> object:
    return raw


async def read(cache: Cache, loader: Loader) -> object:
    return await cache.get_or_load(MODEL, ARGS, loader, encode=encode, decode=decode)


async def test_a_miss_loads_and_stores_the_value_for_the_ttl() -> None:
    # Arrange
    store, loader = MemoryStore(), Loader({"id": "a1", "at": AT})

    # Act
    result = await read(ReadCache(store), loader)

    # Assert
    assert (result, loader.count, store.ttls) == (
        {"id": "a1", "at": AT},
        1,
        {cache_key(MODEL, ARGS): CACHE_TTL_SECONDS},
    )


async def test_a_hit_returns_the_decoded_value_and_does_not_load() -> None:
    # Arrange
    store = MemoryStore()
    store.data[cache_key(MODEL, ARGS)] = serialize({"id": "a1", "at": AT})
    loader = Loader("never used")

    # Act
    result = await read(ReadCache(store), loader)

    # Assert
    assert (result, loader.count) == ({"id": "a1", "at": AT}, 0)


async def test_a_second_read_is_a_hit() -> None:
    # Arrange
    cache, loader = ReadCache(MemoryStore()), Loader({"id": "a1"})
    await read(cache, loader)

    # Act
    result = await read(cache, loader)

    # Assert
    assert (result, loader.count) == ({"id": "a1"}, 1)


async def test_none_is_returned_and_not_stored() -> None:
    # Arrange
    store, loader = MemoryStore(), Loader(None)

    # Act
    result = await read(ReadCache(store), loader)

    # Assert
    assert (result, store.data) == (None, {})


@pytest.mark.parametrize(
    "stored",
    ["not json", '{"$cacheType":"Unknown","value":"x"}', '{"$cacheType":"Bytes"}'],
    ids=["not-json", "unknown-tag", "missing-value"],
)
async def test_an_unreadable_entry_is_reloaded_and_overwritten(stored: str) -> None:
    # Arrange
    store, loader = MemoryStore(), Loader({"id": "a1"})
    key = cache_key(MODEL, ARGS)
    store.data[key] = stored

    # Act
    result = await read(ReadCache(store), loader)

    # Assert
    assert (result, loader.count, store.data[key]) == (
        {"id": "a1"},
        1,
        serialize({"id": "a1"}),
    )


async def test_an_entry_the_decoder_rejects_is_reloaded() -> None:
    # Arrange
    store, loader = MemoryStore(), Loader({"id": "a1"})
    store.data[cache_key(MODEL, ARGS)] = serialize({"old": "shape"})

    def strict(raw: object) -> object:
        raise ValueError("a field is missing")

    # Act
    result = await ReadCache(store).get_or_load(
        MODEL, ARGS, loader, encode=encode, decode=strict
    )

    # Assert
    assert (result, loader.count) == ({"id": "a1"}, 1)


async def test_an_unreachable_redis_serves_the_read_and_logs_without_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    store = MemoryStore(fail_with=RedisConnectionError("boom a1@example.test"))
    loader = Loader({"email": "a1@example.test"})

    # Act
    with caplog.at_level(logging.WARNING, logger="app.core.cache"):
        result = await read(ReadCache(store), loader)

    # Assert
    assert (result, [r.getMessage() for r in caplog.records], store.calls) == (
        {"email": "a1@example.test"},
        ["read cache read failed: ConnectionError"],
        ["get"],
    )


async def test_a_failed_write_is_logged_and_the_value_is_still_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    store = MemoryStore(fail_with=TimeoutError(), fail_on="set")
    loader = Loader({"id": "a1"})

    # Act
    with caplog.at_level(logging.WARNING, logger="app.core.cache"):
        result = await read(ReadCache(store), loader)

    # Assert
    assert (result, [r.getMessage() for r in caplog.records]) == (
        {"id": "a1"},
        ["read cache write failed: TimeoutError"],
    )


async def test_an_error_that_is_not_an_outage_propagates() -> None:
    # Arrange
    store = MemoryStore(fail_with=ResponseError("OOM command not allowed"))

    # Act / Assert
    with pytest.raises(ResponseError):
        await read(ReadCache(store), Loader({"id": "a1"}))


async def test_a_wrong_password_propagates_and_is_not_taken_for_an_outage() -> None:
    # Arrange
    store = MemoryStore(fail_with=AuthenticationError("invalid password"))

    # Act / Assert
    with pytest.raises(AuthenticationError):
        await read(ReadCache(store), Loader({"id": "a1"}))


async def test_invalidate_deletes_the_keys_of_one_model_only() -> None:
    # Arrange
    store = MemoryStore()
    cache = ReadCache(store)
    for model in ("Account", "AccountRole", "Account"):
        await cache.get_or_load(
            model,
            {"n": len(store.data)},
            Loader({"x": 1}),
            encode=encode,
            decode=decode,
        )

    # Act
    deleted = await cache.invalidate("Account")

    # Assert
    assert (deleted, sorted(k.split("*")[1] for k in store.data)) == (
        2,
        ["AccountRole"],
    )


async def test_invalidate_deletes_in_batches() -> None:
    # Arrange
    store = MemoryStore()
    total = DELETE_BATCH_SIZE + 5
    for number in range(total):
        store.data[cache_key(MODEL, {"n": number})] = "{}"

    # Act
    deleted = await ReadCache(store).invalidate(MODEL)

    # Assert
    assert (deleted, store.delete_batches, store.data) == (
        total,
        [DELETE_BATCH_SIZE, 5],
        {},
    )


async def test_invalidate_with_redis_down_logs_and_returns_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    store = MemoryStore(fail_with=RedisConnectionError("down"))

    # Act
    with caplog.at_level(logging.WARNING, logger="app.core.cache"):
        deleted = await ReadCache(store).invalidate(MODEL)

    # Assert
    assert (deleted, [r.getMessage() for r in caplog.records]) == (
        0,
        ["read cache invalidate failed: ConnectionError"],
    )


async def test_the_null_cache_always_loads_and_stores_nothing() -> None:
    # Arrange
    cache, loader = NullReadCache(), Loader({"id": "a1"})

    # Act
    first = await read(cache, loader)
    await read(cache, loader)

    # Assert
    assert (first, loader.count, await cache.invalidate(MODEL)) == ({"id": "a1"}, 2, 0)
