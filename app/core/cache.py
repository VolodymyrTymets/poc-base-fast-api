"""The Redis read cache: a type-preserving serializer, the key builder and the read-through `ReadCache`. Tasks: 9.1, 9.2 (ADR-0034, ADR-0035).

Plain JSON turns a `datetime` or a `Decimal` into a string and refuses `bytes`, so a cache hit would hand a service different
types than a database read does. Each such value is wrapped in a tag on the way in and rebuilt on the way out, so a hit and a
miss have the same shape. `ReadCache` is the read-through layer over a `CacheStore`: a cache never fails a read, so a Redis outage is
logged and the read goes to the database (ADR-0035).
"""

import base64
import binascii
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import AuthenticationError, AuthorizationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config import Settings

logger = logging.getLogger(__name__)

TAG = "$cacheType"

# Scope doc 9.1 and the Node base: an entry is fresh for 60 s and may be served stale for 30 s more.
CACHE_TTL_SECONDS = 60
CACHE_STALE_SECONDS = 30
CACHE_KEY_PREFIX = "cache"
CACHE_KEY_DELIMITER = "*"

# A JSON reader that parses numbers as doubles (any non-Python one) keeps an integer exactly only up to 2**53 - 1, so a larger
# one is tagged as text. Python's own `int` is unbounded; this is parity with the Node base's `BigInt` tag.
MAX_PLAIN_INT = 2**53 - 1


class CacheDecodeError(ValueError):
    """A stored entry cannot be rebuilt: not JSON, or a tag this version did not write. The caller treats it as a miss."""


def _tagged(kind: str, value: str) -> dict[str, str]:
    return {TAG: kind, "value": value}


def _encode(value: object) -> object:
    # Exact types only: a StrEnum or IntEnum member (AccountRoleType) is a str or int subclass that would come back as the plain
    # str or int, so a hit would differ from a database read. It raises TypeError below instead; the caller converts it first.
    if value is None or type(value) in (bool, str, float):
        return value
    if type(value) is int:
        return value if abs(value) <= MAX_PLAIN_INT else _tagged("BigInt", str(value))
    if isinstance(value, datetime):
        return _tagged("DateTime", value.isoformat())
    if isinstance(value, Decimal):
        return _tagged("Decimal", str(value))
    if isinstance(value, bytes):
        return _tagged("Bytes", base64.b64encode(value).decode("ascii"))
    if isinstance(value, list | tuple):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        encoded: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"cache dict keys must be str, got {type(key).__name__}"
                )
            if key == TAG:
                # It would be read back as a tag, so a stored value of another shape would come out.
                raise ValueError(f"a cached dict may not use the key {TAG!r}")
            encoded[key] = _encode(item)
        return encoded
    raise TypeError(f"{type(value).__name__} cannot be cached")


def _dumps(value: object, *, sort_keys: bool) -> str:
    # NaN and infinity floats are not JSON; refusing them (ValueError) keeps an entry readable by any parser.
    return json.dumps(
        _encode(value), allow_nan=False, sort_keys=sort_keys, separators=(",", ":")
    )


def serialize(value: object) -> str:
    """The cache text for `value`: JSON, with `datetime`, `Decimal`, `bytes` and big ints tagged.

    Raises `TypeError` for any other type and `ValueError` for a NaN float or a dict with the key `$cacheType`.
    """
    return _dumps(value, sort_keys=False)


_INT_TEXT = re.compile(r"-?[0-9]+", re.ASCII)


def _decode_tagged(obj: dict[str, object]) -> object:
    kind = obj.get(TAG)
    text = obj.get("value")
    # The encoder writes exactly these two keys; anything else is not an entry of this version.
    if obj.keys() != {TAG, "value"} or not isinstance(text, str):
        raise CacheDecodeError(f"cache tag {kind!r} is not a {TAG}/value pair")
    try:
        if kind == "DateTime":
            return datetime.fromisoformat(text)
        if kind == "Decimal":
            return Decimal(text)
        if kind == "Bytes":
            return base64.b64decode(text, validate=True)
        if kind == "BigInt" and _INT_TEXT.fullmatch(text):
            return int(text)
    except (ValueError, InvalidOperation, binascii.Error) as error:
        raise CacheDecodeError(f"cache tag {kind!r} holds a bad value") from error
    raise CacheDecodeError(f"unknown or bad cache type tag: {kind!r}")


def _hook(obj: dict[str, object]) -> object:
    return _decode_tagged(obj) if TAG in obj else obj


def deserialize(text: str) -> object:
    """Rebuild what `serialize` wrote. Raises `CacheDecodeError` for text that is not JSON or holds an unknown or bad tag."""
    try:
        return json.loads(text, object_hook=_hook)
    except json.JSONDecodeError as error:
        raise CacheDecodeError("cache entry is not valid JSON") from error


# Characters that mean something in a Redis `SCAN MATCH` glob. A model name holding one would make the invalidation pattern match
# other models (`*`, `?`, `[`) or too few (`\\`), so `cache_key` refuses it.
_GLOB_CHARACTERS = frozenset("*?[]\\")


def _check_model(model: str) -> None:
    if not model or _GLOB_CHARACTERS & set(model):
        raise ValueError(
            "a cache model name is not empty and has no glob character (* ? [ ] \\)"
        )


def cache_key(model: str, args: object) -> str:
    """The key `cache*<model>*<sha256 hex of the args>` of one read.

    The hash is over the args serialized with sorted keys, so the same arguments in any dict order give one key, and a `datetime`
    or `bytes` in them hashes by value. Invalidation (task 9.2) scans `invalidation_pattern(model)`.
    """
    _check_model(model)
    digest = hashlib.sha256(_dumps(args, sort_keys=True).encode("utf-8")).hexdigest()
    return CACHE_KEY_DELIMITER.join((CACHE_KEY_PREFIX, model, digest))


def invalidation_pattern(model: str) -> str:
    r"""The `SCAN MATCH` pattern for every key of `model`: `cache\*Account\**`.

    The delimiter is also the glob wildcard, so the two literal ones are escaped; an unescaped `cache*Account*` would match
    `AccountProfile` and `AccountRole` keys too.
    """
    _check_model(model)
    return f"{CACHE_KEY_PREFIX}\\{CACHE_KEY_DELIMITER}{model}\\{CACHE_KEY_DELIMITER}{CACHE_KEY_DELIMITER}"


# What "Redis is down" looks like, as in `core/queue.py`. Any other RedisError (a full server, a bad command, a bug) must reach the
# caller as itself, and so must a wrong or missing password, which is a configuration fault and not an outage (rule D5).
_UNAVAILABLE = (RedisConnectionError, RedisTimeoutError, OSError)

# One attempt at a connection or a reply may take this long: a read that waits on a dead Redis is slower than the query it saves.
STORE_TIMEOUT_SECONDS = 1.0
# `invalidate` deletes in batches of this many keys so one call never holds a huge argument list.
DELETE_BATCH_SIZE = 500


class CacheStore(Protocol):
    """The four Redis calls the cache needs. Production uses `RedisCacheStore`; unit tests use a small in-memory fake."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ex: int) -> None: ...

    def scan_iter(self, match: str) -> AsyncIterator[str]: ...

    async def delete(self, *keys: str) -> int: ...

    async def close(self) -> None: ...


class RedisCacheStore:
    """`CacheStore` over `redis.asyncio`. The connection opens on the first command, so the app boots with no Redis."""

    def __init__(self, settings: Settings) -> None:
        self._redis = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_database,
            password=(
                settings.redis_password.get_secret_value()
                if settings.redis_password
                else None
            ),
            decode_responses=True,
            socket_connect_timeout=STORE_TIMEOUT_SECONDS,
            socket_timeout=STORE_TIMEOUT_SECONDS,
        )

    async def get(self, key: str) -> str | None:
        value: str | None = await self._redis.get(key)
        return value

    async def set(self, key: str, value: str, *, ex: int) -> None:
        await self._redis.set(key, value, ex=ex)

    def scan_iter(self, match: str) -> AsyncIterator[str]:
        return self._redis.scan_iter(match=match)

    async def delete(self, *keys: str) -> int:
        deleted: int = await self._redis.delete(*keys)
        return deleted

    async def close(self) -> None:
        await self._redis.aclose()


class Cache(Protocol):
    """What a service takes: read through the cache, and drop a model's entries. `ReadCache` and `NullReadCache` implement it."""

    async def get_or_load[T](
        self,
        model: str,
        args: object,
        load: Callable[[], Awaitable[T | None]],
        *,
        encode: Callable[[T], object],
        decode: Callable[[object], T],
    ) -> T | None: ...

    async def invalidate(self, model: str) -> int: ...

    async def close(self) -> None: ...


class NullReadCache:
    """The cache switched off (`CACHE_ENABLED=false`, and every test app by default): every read loads, nothing is stored."""

    async def get_or_load[T](
        self,
        model: str,
        args: object,
        load: Callable[[], Awaitable[T | None]],
        *,
        encode: Callable[[T], object],
        decode: Callable[[object], T],
    ) -> T | None:
        return await load()

    async def invalidate(self, model: str) -> int:
        return 0

    async def close(self) -> None:
        return None


class ReadCache:
    """Read-through cache over a `CacheStore`. It fails open: an unreachable Redis is logged and the read is served by `load`.

    Log lines name the operation and the error class only, never a key, an argument or a value (rules D8 and P4: a cached value
    can hold an email, a phone number or a date of birth).
    """

    def __init__(
        self, store: CacheStore, *, ttl_seconds: int = CACHE_TTL_SECONDS
    ) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds

    async def get_or_load[T](
        self,
        model: str,
        args: object,
        load: Callable[[], Awaitable[T | None]],
        *,
        encode: Callable[[T], object],
        decode: Callable[[object], T],
    ) -> T | None:
        """The cached value for `(model, args)`, or what `load` returns, stored for the TTL. `None` is never stored.

        A hit that cannot be rebuilt (an unknown tag, bad JSON, a value `decode` rejects with a `ValueError`) is a miss and is
        overwritten. `encode` must give a value `serialize` accepts; a `TypeError` from it is a bug and propagates.
        """
        key = cache_key(model, args)
        store_up = True
        try:
            raw = await self._store.get(key)
        except _UNAVAILABLE as error:
            _warn("read", error)
            raw, store_up = None, False
        if raw is not None:
            try:
                return decode(deserialize(raw))
            except ValueError:
                logger.warning("read cache entry unreadable, reloading")
        value = await load()
        # A store that just failed a read is not asked again: that would add a second timeout to the request.
        if value is None or not store_up:
            return value
        text = serialize(encode(value))
        try:
            await self._store.set(key, text, ex=self._ttl_seconds)
        except _UNAVAILABLE as error:
            _warn("write", error)
        return value

    async def invalidate(self, model: str) -> int:
        """Delete every entry of `model` with `SCAN` (never `KEYS`, which blocks Redis) and return how many went.

        Call it after the transaction that changed the data has committed: before that, a concurrent read could cache the old row
        again. An unreachable Redis is logged; the stale entries then live for at most the TTL.
        """
        pattern = invalidation_pattern(model)
        deleted = 0
        batch: list[str] = []
        try:
            async for key in self._store.scan_iter(pattern):
                batch.append(key)
                if len(batch) >= DELETE_BATCH_SIZE:
                    deleted += await self._store.delete(*batch)
                    batch = []
            if batch:
                deleted += await self._store.delete(*batch)
        except _UNAVAILABLE as error:
            _warn("invalidate", error)
        return deleted

    async def close(self) -> None:
        await self._store.close()


def _warn(operation: str, error: Exception) -> None:
    if isinstance(error, AuthenticationError | AuthorizationError):
        # Subclasses of the connection error, but a configuration fault: it must not pass for an outage.
        raise error
    logger.warning("read cache %s failed: %s", operation, type(error).__name__)
