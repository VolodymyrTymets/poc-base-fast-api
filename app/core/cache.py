"""Type-preserving serializer and key builder for the Redis read cache. Task: 9.1 (ADR-0034).

Plain JSON turns a `datetime` or a `Decimal` into a string and refuses `bytes`, so a cache hit would hand a service different
types than a database read does. Each such value is wrapped in a tag on the way in and rebuilt on the way out, so a hit and a
miss have the same shape. The module does no Redis I/O (task 9.2) and imports the standard library only.
"""

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

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
