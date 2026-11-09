# POC-9.1 — Cache serializer and key builder

## Problem
Package 9 adds a Redis read cache. Plain `json.dumps` turns a `datetime` into a string, a `Decimal` into a string or an error and `bytes` into an error, so a cache hit would hand services different types than a database read does. The Node base fixed this with `cacheTransformer` (KAN-14); the Python base has no cache code yet (`app/core/cache.py` does not exist).

## Goal / business value
A pure, tested seam in `app/core/cache.py` that task 9.2 (read-through cache and invalidation) builds on: a type-preserving serializer, the key builder and the TTL constants. Goal 1 (scaffolding): a fork gets a cache that returns the same types on a hit as on a miss. It also settles the open decision "Redis read cache" that the scope doc leaves to this task.

## Scope
- in: `serialize(value) -> str` and `deserialize(text) -> object` for `datetime` (timezone kept), `Decimal` (exact), `bytes`, and `int` beyond ±(2^53 − 1) (so a non-Python reader of the key space does not lose precision); an unknown tag raises `CacheDecodeError`, which a caller treats as a miss; `cache_key(model, args) -> str` shaped `cache*<Model>*<hash of args>`; constants `CACHE_TTL_SECONDS = 60` and `CACHE_STALE_SECONDS = 30`; the Node spec's 5 cases ported to pytest; an ADR; docs.
- **out (explicit):** any Redis I/O, `get`/`set`/`SCAN` invalidation and the read-through wrapper (task 9.2); wiring into services; pagination helpers (9.3); a new runtime dependency (the module imports the standard library only); caching of anything other than the listed types; a cache-hit log hook.

## Acceptance criteria
- [ ] AC1 Given a dict holding an aware `datetime`, when serialized and deserialized, then the result equals the input and its `tzinfo` offset is the same; a naive `datetime` stays naive.
- [ ] AC2 Given a `Decimal("1234.56")` (and `Decimal("1E+3")`, `Decimal("NaN")`), when round-tripped, then the result is a `Decimal` that equals it with the same exponent, not a `str` or `float`.
- [ ] AC3 Given `bytes`, a 2^63 int and plain values (str, None, bool, nested list and dict), when round-tripped, then the result equals the input and `bytes` comes back as `bytes`.
- [ ] AC4 Given `{"$cacheType": "Unknown", "value": "x"}` as text, when deserialized, then `CacheDecodeError` is raised naming the tag; given text that is not JSON it raises `CacheDecodeError` too.
- [ ] AC5 Given a value of any other type (for example `set`, `UUID`) or a dict with the key `$cacheType`, when serialized, then it raises `TypeError` / `ValueError`; nothing is stored silently as a wrong shape (rule D5).
- [ ] AC6 Given the same model and the same args in any key order, when `cache_key` is called, then the key is identical and has the form `cache*Account*<64 hex>`; different args or model give different keys; `*` in a model name is rejected.
- [ ] AC7 `CACHE_TTL_SECONDS == 60` and `CACHE_STALE_SECONDS == 30`.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| a user dict that already has `$cacheType` and `value` keys | `serialize` raises `ValueError` (it would be read back as a tag) | plan |
| `bool` is an `int` subclass | stays a JSON boolean, never tagged | plan |
| int of exactly ±(2^53 − 1) / one beyond | plain / tagged | plan |
| args holding a `datetime` or `bytes` | hashed through the same serializer, so the key is stable | plan |
| entry written by another version (unknown tag) | `CacheDecodeError`, caller treats as a miss | Node KAN-14, scope doc |

## Open questions
| # | Question | Assumed answer | Needs a human? |
|---|----------|----------------|----------------|
| Q1 | Keep the Redis read cache in this base at all? (scope doc: "decided in task 9.1"; I.8-style staleness risk, Redis is also the arq queue backend) | Yes: build it, as package 9 and the BUSINESS_MODEL "Not built" list assume | **yes** |
| Q2 | Which hash for the key? | sha256 hex of the canonical JSON (sorted keys) of the args | no |
| Q3 | Is a new ADR needed? | Yes, ADR-0034: serializer tags, key shape, TTLs, unknown tag is a miss; it ports the decision of Node ADR-0001 amendment KAN-14 | no |
