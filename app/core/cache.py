"""Type-preserving serializer and key builder for the Redis read cache. Task: 9.1 (ADR-0034).

Plain JSON turns a `datetime` or a `Decimal` into a string and refuses `bytes`, so a cache hit would hand a service different
types than a database read does. Each such value is wrapped in a tag on the way in and rebuilt on the way out, so a hit and a
miss have the same shape. The module does no Redis I/O (task 9.2) and imports the standard library only.
"""

import base64
import binascii
import hashlib
import json
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
    # bool is an int subclass and must stay a JSON boolean, so it is checked before int.
    if value is None or isinstance(value, bool | str | float):
        return value
    if isinstance(value, int):
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


def _decode_tagged(obj: dict[str, object]) -> object:
    kind = obj.get(TAG)
    text = obj.get("value")
    if not isinstance(text, str):
        raise CacheDecodeError(f"cache tag {kind!r} has no text value")
    try:
        if kind == "DateTime":
            return datetime.fromisoformat(text)
        if kind == "Decimal":
            return Decimal(text)
        if kind == "Bytes":
            return base64.b64decode(text, validate=True)
        if kind == "BigInt":
            return int(text)
    except (ValueError, InvalidOperation, binascii.Error) as error:
        raise CacheDecodeError(f"cache tag {kind!r} holds a bad value") from error
    raise CacheDecodeError(f"unknown cache type tag: {kind!r}")


def _hook(obj: dict[str, object]) -> object:
    return _decode_tagged(obj) if TAG in obj else obj


def deserialize(text: str) -> object:
    """Rebuild what `serialize` wrote. Raises `CacheDecodeError` for text that is not JSON or holds an unknown or bad tag."""
    try:
        return json.loads(text, object_hook=_hook)
    except json.JSONDecodeError as error:
        raise CacheDecodeError("cache entry is not valid JSON") from error


def cache_key(model: str, args: object) -> str:
    """The key `cache*<model>*<sha256 hex of the args>` of one read.

    The hash is over the args serialized with sorted keys, so the same arguments in any dict order give one key, and a `datetime`
    or `bytes` in them hashes by value. Invalidation (task 9.2) scans `cache*<model>*`, so the model name may not hold the delimiter.
    """
    if not model or CACHE_KEY_DELIMITER in model:
        raise ValueError(
            f"a cache model name is not empty and has no {CACHE_KEY_DELIMITER!r}"
        )
    digest = hashlib.sha256(_dumps(args, sort_keys=True).encode("utf-8")).hexdigest()
    return CACHE_KEY_DELIMITER.join((CACHE_KEY_PREFIX, model, digest))
