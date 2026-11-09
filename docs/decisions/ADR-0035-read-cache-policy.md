# ADR-0035 — Read cache policy: which reads, invalidation after the commit, fail open, `CACHE_ENABLED`

- **Date:** 2026-11-09
- **Status:** accepted
- **Deciders:** Volodymyr (approved the plan of POC-9.2, which stated defaults for Q1, Q2 and Q3; the review of the first draft removed the role cache from it, below)
- **Ticket:** POC-9.2
- **Supersedes:** nothing. It builds on ADR-0034 (codec and keys) and ADR-0027 (a service may be built from a core seam); it changes two bullets of the scope doc's row 9.2 (the standalone profile read and the roles are not cached) and does not use `fakeredis` or the 30 s stale window.

## Context
ADR-0034 gave the base a codec and keys but no Redis I/O. Task 9.2 puts reads on it. Three facts shape the policy: the services return ORM objects, which the codec cannot store; some reads feed a write or an authentication decision, where a stale value is a fault, not a delay; and Redis is also the arq queue, so it may be down, absent or writable by anything that can reach it.

## Decision
- **A cache is a seam, not a decorator on every read.** `app/core/cache.py` has `ReadCache` (read-through over a `CacheStore`), `NullReadCache` (stores nothing) and the `Cache` protocol a service takes. `ReadCache.get_or_load(model, args, load, encode, decode)` returns the decoded entry on a hit; on a miss it runs `load`, stores `serialize(encode(value))` for 60 s (`CACHE_TTL_SECONDS`) and returns the value. `None` is never stored.
- **Only reads that no write or authentication decision depends on are cached, and they return plain data.**
  - Cached: `AccountService.get_snapshot` (the account with its live profile as an `AccountResponse`, for `GET /account`) under model `Account`. Nothing else.
  - Never cached: `AccountRoleService.get_account_roles` (`require_roles` decides access on it, and the cache has no integrity check: anyone who can write to Redis, which has no password in the compose stack, could `SET` the key, a public sha256 of the account id, to `["ADMIN"]` and pass an admin route; the first draft cached it and the review found this), `AccountService.get_by_id` and `get_by_phone` (sign-in and seeds), and `AccountProfileService.get_by_account_id` (read-modify-write in `update`, and the notifier, which picks the phone or email a code goes to). A service built with no cache (seeds, write paths, `AccountService._create`, every service but `AccountService` today) gets `NullReadCache`. A forged snapshot can change only what `GET /account` shows its own caller.
- **Invalidate after the commit, one key.** `ReadCache.forget(model, args)` deletes one entry with a single `DEL`; `AccountService.forget_snapshot(account_id)` wraps it, and `PATCH /accounts/{accountId}/profile` calls it after `session.commit()`. A failed update raises before it and leaves the entry alone. `ReadCache.invalidate(model)` deletes every key of `invalidation_pattern(model)` with `SCAN` in batches of 500 (never `KEYS`) for a write that changes many records; no route uses it, because a scan walks the whole Redis database the queue shares and a client can call the PATCH in a loop (no rate limit, issue I.8).
- **The race that remains.** Invalidating after the commit narrows the window and does not close it: a read that missed and loaded the old row before the commit may store it after the `DEL`, and that entry is served until its TTL (60 s). Closing it needs a per-account version in the key or a write marker; neither is built (the cost is a stale `GET /account` of at most 60 s for the caller who just changed their own profile).
- **Fail open, for every store failure.** Any `RedisError` or `OSError` (an outage, a full Redis refusing writes with `OOM`, a read-only replica after a failover, a wrong password) is logged (`read cache <read|write|forget|invalidate> failed: <ErrorClass>`: no key, no argument, no value) and the read is served by `load`; a write that already committed never turns into a 500 because the cache could not be cleaned. The class name in the log is how a misconfiguration is seen (rule D5). After a failed read the store is not asked to write, so a request pays at most one timeout (1 s per attempt, no retries). A hit that cannot be rebuilt (`CacheDecodeError`, or a `ValueError` from `decode`) is a miss and is overwritten. This differs from `core/queue.py`, which lets a wrong password through: a queue that cannot enqueue loses a job, a cache that cannot read loses nothing.
- **`CACHE_ENABLED`** (default `true`, in both env templates): `create_app` builds `ReadCache(RedisCacheStore(settings))` on the queue's Redis, or `NullReadCache`. The Redis connection opens on the first command, so the app boots with no Redis. The test environment sets it to `false` (autouse fixture in `tests/conftest.py`); a test that wants the cache passes `cache_enabled=True`.
- **The stale window is not built.** An entry older than 60 s is gone (Redis `EX`); `CACHE_STALE_SECONDS` (30, ADR-0034) stays defined and unused. Stale-while-revalidate would need a background task with its own database session.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Cache `AccountProfileService.get_by_account_id` too (the scope row) | its callers are `update` (needs a live ORM row) and the notifier (a stale phone or email sends a sign-in code or a reset token to the wrong place) |
| A decorator on every service method | hides which reads are cached; the two reads here need their own encode and decode |
| `fakeredis` in tests | a new dev dependency (rule C2); real Redis already exists in the test base (`redis_settings`, index 15), and a hand-written `MemoryStore` covers the unit cases |
| Cache the roles (the first draft) | forgeable by whoever can write to Redis, see above; the saving is one indexed query per guarded request |
| `invalidate("Account")` on every profile update (the first draft) | a `SCAN` over the whole Redis database per request, callable in a loop by any customer, and it empties every account's entry |
| Invalidate inside the service, before the commit | a read between the invalidation and the commit caches the old row for another 60 s |
| Fail closed or propagate "configuration" errors (a 500 for a wrong password or a full Redis) | the cache is derived data; the first draft let these through and a misconfigured queue Redis would have turned every `GET /account` and every PATCH into a 500 |
| Stale-while-revalidate | see above; the gain is a latency cut on a 60 s window, for a background session and a race to reason about |

## Consequences
- Positive: `GET /account` is served from Redis after the first read; a cache outage costs one logged warning and one 1 s timeout at most; the seam is testable without Redis (unit) and with it (HTTP).
- Accepted cost: after a write that bypasses the PATCH route (none exists), up to 60 s of stale data; the snapshot holds email, phone number and date of birth in Redis for up to 60 s, next to job arguments that already hold reset tokens, so a Redis that is reachable from outside leaks both (the compose stack publishes it on loopback only, ADR-0031); a soft-deleted account is served from the cache for up to 60 s (no delete route exists); `isPhoneVerified` is in the snapshot and the sign-in code verification sets it without forgetting the entry, which is safe today (no token exists before the first verify, so no snapshot) and must change if a flow lets a signed-in account change its phone.
- Follow-ups: a route that changes an account or its profile calls `forget_snapshot` after its commit; caching the roles needs an integrity check (a signed value or a Redis password required while the cache is on) and a new ADR; if a fork needs stale-while-revalidate it supersedes this ADR.

## Revisit when
A stale-read bug appears, a second cached read is proposed that a write depends on, or Redis stops being shared with the queue.
