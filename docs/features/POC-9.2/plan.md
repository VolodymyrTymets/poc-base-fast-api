# POC-9.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-09 (approved in session, recorded by Claude at their instruction; Q1, Q2 and Q3 answered by approving the stated defaults: the narrower set of cached reads, no fakeredis, no stale-while-revalidate)

Pattern followed: `app/core/queue.py` (a `core` seam over Redis with a protocol, a real implementation, fail-open and loud-failure rules, `redis.asyncio` already imported there), the providers of ADR-0025 and the "after the commit" rule of `backend-fastapi.md` 17 (tasks 7.1, 7.6), `FakeQueue` / `redis_settings` for the tests, and the Node `cached-reads.e2e-spec.ts` for the two flows.
New pattern: a service built from a core seam with a null default (`ReadCache`): ADR-0027 allows services built from core seams; the cache policy gets ADR-0035 (rule D1).

## Contract changes
- boundary: none (no route added or changed; `openapi.json` unchanged). The PATCH route gains an invalidation call after its commit.
- data: none. No migration.
- config: new setting `CACHE_ENABLED` (default `true`) in `Settings`, `.env.example`, `.env.development.example` (ARCHITECTURE and RUNBOOK follow).
- dependencies: none declared (`redis` comes with `arq` and is already imported in `app/core/queue.py`); `fakeredis` not added (Q2).
- generated output: none.

## Requirements (ordered; branch `feat/POC-9.2-read-cache`, one draft PR, one commit each)

### R1 — `ReadCache`, `NullReadCache` and the fail-open rules (M)
- files: `app/core/cache.py` (change: `CacheStore` protocol (`get`, `set(key, value, ex)`, `scan_iter(match)`, `delete(*keys)`), `ReadCache(store)` with `get_or_load` / `invalidate`, `NullReadCache`, `RedisCacheStore` over `redis.asyncio.Redis` from `Settings`; errors in `_UNAVAILABLE` of `core/queue.py` style are caught and logged, any other `RedisError` propagates as itself (rule D5)); `app/config.py` (change: `cache_enabled`); `.env.example`, `.env.development.example` (ask-first? no, they are not protected: `!**/.env.*example`)
- layer: core, config
- test: `tests/unit/test_read_cache.py` (new, a hand-written in-memory store that fails loudly on a wrong call): hit returns decoded value and does not call the loader; miss loads and stores with the TTL; `None` is not stored (AC8); unreadable entry is a miss and is overwritten (AC5); store errors on get, set and scan are logged without keys and values and the read still returns (AC4 at unit level); `invalidate` deletes only matching keys and uses `scan_iter`, never `keys` (AC6); `NullReadCache` always loads. `tests/unit/test_config.py` (change: the setting).
- executed how: `uv run pytest tests/unit/test_read_cache.py`; the real Redis run is R4
- risk: `redis.asyncio` raises more error types than the three `_UNAVAILABLE` ones; each unexpected one must propagate. Tested with a fake that raises `ResponseError`.

### R2 — Wiring (S)
- files: `app/main.py` (change: build `app.state.cache` from the settings, close its Redis in the lifespan, the position stated in a comment), `app/dependencies.py` (change: `get_read_cache`; `get_account_service` and `get_account_role_service` take it), `tests/conftest.py` (change: `asgi_app` builds the app with `cache_enabled=False`, so a database test never reaches Redis)
- layer: main, dependencies, tests
- test: `tests/unit/test_run.py` or a new `tests/unit/test_cache_wiring.py`: `create_app(Settings(cache_enabled=False))` has a `NullReadCache`; with it on, a `ReadCache` and no connection opened at build time (as the queue pool)
- executed how: `uv run pytest tests/unit`; app boots with Redis down (`uv run poc-base-fast-api`, health 200)
- risk: a service built twice per request (`AccountService` builds `AccountRoleService` in `_create`): the inner one takes the null cache, because that path writes.

### R3 — Cached reads (M)
- files: `app/services/account.py` (change: constructor `cache: ReadCache | None = None` as a keyword (null when omitted); `get_snapshot(account_id)` = `get_or_load("Account", {"accountId": id}, load, encode, decode)` where `load` is `get_by_id` then `AccountResponse.model_validate`, encode is `model_dump()`, decode is `model_validate`; `get_by_id` stays uncached), `app/services/account_role.py` (change: the same for `get_account_roles` under model `AccountRole`; encode to the enum values, decode back to `AccountRoleType`), `app/routers/account.py` (change: `read_account` calls `get_snapshot`)
- layer: services, routers
- test: `tests/integration/db/test_db_account_service.py` and `test_db_account_role_service.py` (change): with a `ReadCache` over the hand-written store, the second call does not query (a counter on `before_cursor_execute`), equals the first, `created_at` is a `datetime`, roles are `AccountRoleType`; the cache-off service behaves as before (the existing tests are the proof)
- executed how: `uv run pytest tests/integration/db/test_db_account_service.py tests/integration/db/test_db_account_role_service.py`; HTTP in R4
- risk: `AccountResponse.model_dump()` must hold only codec types (a `StrEnum` field raises `TypeError`, 9.1 review); checked by the first test, with `mode="json"` as the fallback if a profile field is an enum.

### R4 — Invalidation on write and the end-to-end flows (M)
- files: `app/routers/account_profile.py` (change: after `await session.commit()`, `await cache.invalidate("Account")`), `tests/integration/http/test_http_read_cache.py` (new, real Redis through `redis_settings`, real Postgres)
- layer: routers, tests
- test: AC1 and AC2 over HTTP with a query counter; AC3 through a guarded route; AC4 with the Redis port closed (answers 200, one warning, no id in the log via `caplog`); AC6 against real Redis (`SCAN`, the other model's key survives); AC7 (`cache_enabled=False` opens no connection)
- executed how: the real server with Postgres and Redis: sign in by OTP, `curl GET /account` twice with the debug log showing hit then miss, `PATCH` the profile, `GET` again (miss, new value); stop Redis and repeat (200); output pasted in the PR
- risk: the invalidation must not run when the commit fails: it sits after it, tested by a PATCH that is a 409 and leaves the cache intact.

## Docs to update in this PR
- [x] docs/features/POC-9.2/spec.md (acceptance criteria checked off)
- [x] docs/decisions/ADR-0035-read-cache-policy.md (new)
- [x] docs/ARCHITECTURE.md — `core/cache.py` row, "No cache is wired" paragraph, the cached reads, Decided and Planned bullets
- [x] docs/RUNBOOK.md — a "Read cache" section: the setting, what is cached, fail open, how to flush by hand (`SCAN`, not `FLUSHALL`: it drops queued jobs), the 60 s staleness and the personal data in Redis
- [x] docs/DOMAIN_GLOSSARY.md — "Read cache", "Snapshot"
- [x] docs/BUSINESS_MODEL.md — status line
- [x] `.claude/rules/backend-fastapi.md` — one rule: a read goes through the cache only when no write or authentication decision reads it; invalidate after the commit (ask-first path: `.claude/**`)
- [ ] `.env.example`, `.env.development.example` — `CACHE_ENABLED` (edited; not committed: the A6 guard hook blocks staging them, see the PR)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Q1 answered "cache the standalone profile read too" | the notifier could send a code to a phone changed up to 60 s earlier | the human answers Q1 at approval |
| An authorization read served stale | a removed role still passes `require_roles` for up to 60 s | no role-change route exists; ADR-0035 and the backend rule require invalidation in any future one |
| Personal data (email, phone, DOB) in Redis | a leak of Redis shows 60 s of profiles | stated in the ADR and RUNBOOK; the Redis is local-only in the compose stack (ADR-0031) |
| Redis down adds latency to every read | a connect timeout per request | the pool is lazy and one attempt fails at once, as the queue (RUNBOOK); measured in R4 |
| `FLUSHALL` for cache cleanup drops the arq queue | lost jobs | RUNBOOK says `SCAN` + delete by pattern |

## Assumptions
- Spec Q4 and Q5; Q1, Q2 and Q3 need a human.
- 9.1 is merged (PR #46, `bcd5dc5` on `main`); the branch starts from it. The untracked `Scope Breakdown ... .md`, `.serena/` and `dump.rdb` are not part of this PR.
- The scope row's file list (`app/services/account*.py`) holds; the extra files are `app/main.py`, `app/dependencies.py`, `app/config.py`, `app/routers/*`, the env templates and tests.

## Deviations (found while implementing, recorded here and in the PR)
- R1: the cache protocol is `Cache` (with `ReadCache` and `NullReadCache` implementing it), not `ReadCache | None`; a service takes `cache: Cache | None = None` as a keyword and uses `NullReadCache` when omitted.
- R2: the read cache is switched off for every test app by the autouse `isolated_settings_env` fixture (`CACHE_ENABLED=false`), not only in `asgi_app`, because many tests build `create_app(Settings(...))` themselves.
- R3: `tests/integration/http/test_http_service_providers.py` changed (unplanned): its fake account service provided `get_by_id`, and `GET /account` now calls `get_snapshot`. The assertions are unchanged.
- R3: shared test helpers `tests/utils/cache.py` (`MemoryStore`, moved out of the unit test) and `tests/utils/sql.py` (`count_statements`).
- R4: `PATCH /accounts/{accountId}/profile` calls `AccountService.forget_snapshot` (through `get_account_service`), not `cache.invalidate("Account")`.
- Review (blocking): the role cache was removed. Anyone who can write to the queue's Redis could `SET` `cache*AccountRole*<sha256 of the account id>` to `["ADMIN"]` and pass `require_roles`; the plan accepted stale roles and never considered forged ones. `AccountRoleService` is back to what `main` has; regression tests: roles are never served from Redis, and a forged entry gives 403. This narrows the approved Q1 set further (the approval named roles as cached); it needs your confirmation.
- Review: every `RedisError` or `OSError` is a store failure that is logged and ignored (the first draft let a full Redis or a wrong password through, which would have made `GET /account` and the PATCH answer 500); `ReadCache.forget` (one `DEL`) replaces the model-wide `invalidate` on the PATCH (a `SCAN` over the queue's Redis per request, callable in a loop); the ADR states the race that invalidating after the commit does not close.
