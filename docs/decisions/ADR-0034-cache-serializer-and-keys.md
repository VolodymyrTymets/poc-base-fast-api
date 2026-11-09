# ADR-0034 — Redis read cache: tagged-JSON serializer, `cache*<Model>*<hash>` keys, 60 s TTL and 30 s stale window

- **Date:** 2026-11-09
- **Status:** accepted
- **Deciders:** Volodymyr (approved the plan of POC-9.1, which stated "keep the cache" as its default for the question the scope doc left to this task)
- **Ticket:** POC-9.1
- **Supersedes:** nothing. It ports the amendment KAN-14 of the Node base's ADR-0001 (`cacheTransformer`); the Node ADR stays in force there. It adds `app/core/cache.py` (rule 3 of ADR-0011: one module per concern).

## Context
The scope doc keeps a Redis read cache (package 9) and leaves "keep it or not" to task 9.1. Plain JSON turns a `datetime` or `Decimal` into a string and refuses `bytes`, so a cache hit would give a service other types than a database read does; the Node base hit exactly this (`from.getTime is not a function`).

## Decision
- **The cache is kept.** Task 9.2 builds the read-through wrapper and the invalidation; 9.1 is the pure seam under it, standard library only, no Redis I/O, no new dependency.
- **Serializer.** `serialize` / `deserialize` in `app/core/cache.py` write JSON and wrap `datetime` (ISO 8601, offset kept; a naive one stays naive), `Decimal` (its `str`, so the exponent survives), `bytes` (base64) and an `int` beyond ±(2^53 − 1) (text, for parity with the Node `BigInt` tag and for readers that parse numbers as doubles) as `{"$cacheType": <kind>, "value": <text>}`. Tuples come back as lists. Only the exact types `bool`, `int`, `float` and `str` are written plain: a `StrEnum` member such as `AccountRoleType.ADMIN` would come back as a plain `str`, so it is a `TypeError` too. Any other type is a `TypeError`, a non-string dict key a `TypeError`, a NaN float and a dict that already has the key `$cacheType` a `ValueError`: nothing is stored in a shape that would read back as something else (rule D5).
- **An entry that cannot be rebuilt is a miss.** Text that is not JSON, an unknown tag (an entry another version wrote), a tagged object with keys other than `$cacheType` and `value`, or a bad tagged value raises `CacheDecodeError`; the caller (9.2) treats it as a miss and does not return a record with a field dropped.
- **Keys.** `cache_key(model, args)` is `cache*<model>*<sha256 hex>` of the args serialized with sorted keys, so dict order does not matter. The delimiter is `*` as in the Node base; the delimiter is also the glob wildcard of `SCAN MATCH`, so `invalidation_pattern(model)` returns the escaped `cache\*<model>\**` (an unescaped `cache*Account*` would also match `AccountProfile` keys), and a model name that is empty or holds a glob character (`* ? [ ] \`) is a `ValueError`. Task 9.2 scans with it, with `SCAN`, never `KEYS`.
- **Freshness.** `CACHE_TTL_SECONDS = 60` and `CACHE_STALE_SECONDS = 30`, the Node values.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `pickle` | executes code on read from a shared Redis; ADR-0005 already keeps job payloads JSON |
| Pydantic `model_dump_json` / `TypeAdapter` | needs a schema per cached read, and the cache also keys on plain-dict args; a tagged codec needs none. Either way task 9.2 turns an ORM row into a dict before caching |
| `orjson` or `msgpack` | a new runtime dependency (rule C2) for a seam that is 100 lines of standard library |
| Hashing with Python's `hash()` | differs per process (hash randomization); a key must be the same in the API and the worker |

## Consequences
- Positive: a hit and a miss have the same types; the seam is unit-tested with no Docker; 9.2 needs no codec of its own.
- Accepted cost: Redis is a second place for stale data, within 90 s at most; a `Decimal("1.0")` and `Decimal("1.00")` in args are different keys; `float` is written as JSON, so `-0.0` and `0.0` differ.
- Follow-ups: 9.2 turns rows into dicts (and enums into their values) before caching, and decides which values are "args" and wires the cache into the service reads; if it needs a Redis client, it asks for approval of the dependency (rule C2).

## Revisit when
The cache causes a stale-read bug, or the codec has to carry a type it refuses today (`date`, `UUID`).
