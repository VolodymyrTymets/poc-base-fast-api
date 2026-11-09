# POC-9.2 — Read-through cache and invalidation

## Problem
Task 9.1 built the codec and the keys (`app/core/cache.py`, ADR-0034) but nothing reads or writes Redis. The scope row asks for a read-through cache on the service reads of account, profile and roles, invalidation by model pattern on writes (`SCAN`, never `KEYS`), and a cache that is off in tests unless a fake Redis is injected. Not every read can be cached safely: the services return ORM objects (not cacheable by the 9.1 codec), and some readers are write paths or authentication paths.

## Goal / business value
Goal 1 (scaffolding) and goal 3 (test base): a fork gets a working read cache whose hits equal the database reads, which fails open when Redis is down, and which is tested without a mock database. The first read on it is the signed-in account (`GET /api/v1/account`); the roles checked by `require_roles` are left out after review (forgeable entry, ADR-0035).

## Scope
- in:
  - `ReadCache` in `app/core/cache.py`: `get_or_load(model, args, load, encode, decode)` (a hit returns the decoded value, a miss runs `load`, stores the encoded result for `CACHE_TTL_SECONDS`), `invalidate(model)` (`SCAN MATCH invalidation_pattern(model)`, deletes in batches), and `NullReadCache` (cache off).
  - Fail open: a Redis connection or timeout error, a `CacheDecodeError` or a failed write is logged (no values, no keys with ids) and the read goes to the database; a read never fails because of the cache.
  - `app/main.py`: `create_app` builds the cache into `app.state.cache` when `CACHE_ENABLED` is true (new setting), closes it in the lifespan; `get_read_cache` in `app/dependencies.py`.
  - Cached reads: `AccountService.get_snapshot(account_id) -> AccountResponse | None` (the account with its live profile; used by `GET /account`) and `AccountRoleService.get_account_roles` (used by `require_roles`). `None` is never cached.
  - Invalidation: `PATCH /accounts/{accountId}/profile` invalidates the `Account` model **after** its commit.
  - Tests on a real Redis (the `redis_settings` fixture) and real Postgres for the two flows of the Node `cached-reads.e2e-spec.ts`, and unit tests of the fail-open paths with a small hand-written fake store.
  - ADR-0035, docs.
- **out (explicit):** caching `AccountProfileService.get_by_account_id` (its readers are `update`, a read-modify-write, and the notifier, which picks the phone or email a code is sent to: a stale value is a security fault) and `AccountService.get_by_phone` (the OTP and seed paths); negative caching; stale-while-revalidate; a role-change endpoint and its invalidation (none exists); list helpers (9.3); a Redis client dependency declaration beyond what `arq` already brings (`core/queue.py` imports `redis` today); `fakeredis`.

## Acceptance criteria
- [x] AC1 Given the cache on, when `GET /account` is called twice for one account, then the second call is served from Redis (the database sees no query for the account) and both bodies are equal, including `createdAt` as a timestamp.
- [x] AC2 Given a cached account, when the profile is updated through `PATCH /accounts/{id}/profile`, then that account's entry is dropped after the commit and the next `GET /account` is a miss and shows the new value; a Redis failure there still answers 200.
- [x] AC3 (changed in review) The roles read by `require_roles` is never cached: a second guarded call runs SQL, and a forged `["ADMIN"]` entry in Redis does not open an admin route.
- [x] AC4 Given Redis is unreachable, when `GET /account` is called, then it answers 200 from the database and one warning is logged with no account id, email or phone.
- [x] AC5 Given an entry that cannot be decoded (unknown tag, bad JSON), when read, then it is a miss, is reloaded and overwritten.
- [x] AC6 Given `invalidate("Account")`, when it runs, then every `cache*Account*…` key is gone and `cache*AccountRole*…` keys remain; it uses `SCAN`, never `KEYS`.
- [x] AC7 Given `CACHE_ENABLED=false`, then no Redis connection is opened and reads hit the database; the default test app has the cache off.
- [x] AC8 Given a `None` result (unknown or soft-deleted account), then nothing is stored.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| invalidation before the commit | not done: it runs after the route's commit, or a concurrent read re-caches the old row | plan (rule: enqueue after commit, backend-fastapi 17) |
| profile updated by another instance | the same Redis, so the same invalidation | plan |
| two reads race a miss | both load and both write the same value; last write wins | plan |
| a write that fails to invalidate (Redis down) | logged; stale entries live at most `CACHE_TTL_SECONDS` | ADR-0035 |
| personal data in Redis | the snapshot holds email, phone and date of birth for at most 60 s, in the Redis the queue already uses; recorded as a consequence in the ADR | ADR-0035 |

## Open questions
| # | Question | Assumed answer | Needs a human? |
|---|----------|----------------|----------------|
| Q1 | The scope row says "account, profile, roles". Cache only the account-with-profile snapshot and the roles, and leave the standalone profile read uncached (reasons above)? | Yes, the narrower set | **yes** |
| Q2 | `fakeredis` (scope row) is a new dev dependency (rule C2). Use real Redis in integration tests plus a small hand-written fake for unit tests instead? | Yes, no new dependency | **yes** |
| Q3 | The 30 s stale window of 9.1: serving a stale entry while refreshing needs a background task with its own session. Skip it (an entry older than the TTL is a miss; `CACHE_STALE_SECONDS` stays defined and unused, recorded in the ADR)? | Yes, skip | **yes** |
| Q4 | A `CACHE_ENABLED` setting, default `true`, in both env templates? | Yes | no |
| Q5 | Is a new ADR needed? | Yes, ADR-0035: which reads are cached and which never, invalidation after commit, fail open, the setting | no |
