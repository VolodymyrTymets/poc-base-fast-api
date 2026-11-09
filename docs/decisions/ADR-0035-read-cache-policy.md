# ADR-0035 — Read cache policy: which reads, invalidation after the commit, fail open, `CACHE_ENABLED`

- **Date:** 2026-11-09
- **Status:** accepted
- **Deciders:** Volodymyr (approved the plan of POC-9.2, which stated these defaults as its answers to Q1, Q2 and Q3)
- **Ticket:** POC-9.2
- **Supersedes:** nothing. It builds on ADR-0034 (codec and keys) and ADR-0027 (a service may be built from a core seam); it changes one bullet of the scope doc's row 9.2 (the standalone profile read is not cached) and does not use `fakeredis` or the 30 s stale window.

## Context
ADR-0034 gave the base a codec and keys but no Redis I/O. Task 9.2 puts reads on it. Three facts shape the policy: the services return ORM objects, which the codec cannot store; some reads feed a write or an authentication decision, where a stale value is a fault, not a delay; and Redis is also the arq queue, so it may be down or absent.

## Decision
- **A cache is a seam, not a decorator on every read.** `app/core/cache.py` has `ReadCache` (read-through over a `CacheStore`), `NullReadCache` (stores nothing) and the `Cache` protocol a service takes. `ReadCache.get_or_load(model, args, load, encode, decode)` returns the decoded entry on a hit; on a miss it runs `load`, stores `serialize(encode(value))` for 60 s (`CACHE_TTL_SECONDS`) and returns the value. `None` is never stored.
- **Only reads that no write or authentication decision depends on are cached, and they return plain data.**
  - Cached: `AccountService.get_snapshot` (the account with its live profile as an `AccountResponse`, for `GET /account`) under model `Account`, and `AccountRoleService.get_account_roles` (for `require_roles`) under model `AccountRole`. An empty role list is not cached.
  - Never cached: `AccountService.get_by_id` and `get_by_phone` (sign-in and seeds), and `AccountProfileService.get_by_account_id` (read-modify-write in `update`, and the notifier, which picks the phone or email a code goes to). A service built with no cache (seeds, write paths, `AccountService._create`) gets `NullReadCache`.
- **Invalidate after the commit, by model.** `ReadCache.invalidate(model)` deletes every key of `invalidation_pattern(model)` with `SCAN` in batches of 500 (never `KEYS`). `PATCH /accounts/{accountId}/profile` calls it for `Account` after `session.commit()`; a failed update raises before it and leaves the entries alone. Before the commit a concurrent read would cache the old row again. Roles change only when an account is created, so nothing invalidates `AccountRole` today; a future route that changes them must invalidate after its commit.
- **Fail open.** A connection error, a timeout or an `OSError` from Redis is logged (`read cache <read|write|invalidate> failed: <ErrorClass>`: no key, no argument, no value) and the read is served by `load`. After a failed read the store is not asked to write, so a request pays at most one timeout (1 s per attempt, no retries). A hit that cannot be rebuilt (`CacheDecodeError`, or a `ValueError` from `decode`) is a miss and is overwritten. Any other `RedisError`, and a wrong or missing password (`AuthenticationError`, `AuthorizationError`), propagate: they are configuration faults, not outages (rule D5; `core/queue.py` makes the same cut).
- **`CACHE_ENABLED`** (default `true`, in both env templates): `create_app` builds `ReadCache(RedisCacheStore(settings))` on the queue's Redis, or `NullReadCache`. The Redis connection opens on the first command, so the app boots with no Redis. The test environment sets it to `false` (autouse fixture in `tests/conftest.py`); a test that wants the cache passes `cache_enabled=True`.
- **The stale window is not built.** An entry older than 60 s is gone (Redis `EX`); `CACHE_STALE_SECONDS` (30, ADR-0034) stays defined and unused. Stale-while-revalidate would need a background task with its own database session.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Cache `AccountProfileService.get_by_account_id` too (the scope row) | its callers are `update` (needs a live ORM row) and the notifier (a stale phone or email sends a sign-in code or a reset token to the wrong place) |
| A decorator on every service method | hides which reads are cached; the two reads here need their own encode and decode |
| `fakeredis` in tests | a new dev dependency (rule C2); real Redis already exists in the test base (`redis_settings`, index 15), and a hand-written `MemoryStore` covers the unit cases |
| Invalidate inside the service, before the commit | a read between the invalidation and the commit caches the old row for another 60 s |
| Fail closed (a 500 when Redis is down) | the cache is derived data; the queue already needs Redis, but a read path should not |
| Stale-while-revalidate | see above; the gain is a latency cut on a 60 s window, for a background session and a race to reason about |

## Consequences
- Positive: `GET /account` and every `require_roles` check are served from Redis after the first read; a cache outage costs one logged warning and one 1 s timeout at most; the seam is testable without Redis (unit) and with it (HTTP).
- Accepted cost: after a write that bypasses the PATCH route (none exists), up to 60 s of stale data; the snapshot holds email, phone number and date of birth in Redis for up to 60 s, next to job arguments that already hold reset tokens, so a Redis that is reachable from outside leaks both (the compose stack publishes it on loopback only, ADR-0031); a soft-deleted account is served from the cache for up to 60 s (no delete route exists); `invalidate("Account")` drops every account's entry, not one.
- Follow-ups: a role-change or account-delete route invalidates after its commit; if a fork needs stale-while-revalidate it supersedes this ADR.

## Revisit when
A stale-read bug appears, a second cached read is proposed that a write depends on, or Redis stops being shared with the queue.
