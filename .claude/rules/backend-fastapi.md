---
description: Backend conventions for the FastAPI app - async, sessions and transactions, services, models, settings, jobs, logging. Restates decided ADRs; it decides nothing.
paths:
  - "app/**"
  - "migrations/**"
---

# Backend (FastAPI, SQLAlchemy, arq)

This file restates decisions that already have an ADR or a rule ID; each line names its source. If a line disagrees with its source, the source wins and you raise it (rule D2). A convention with no source is not written here: it needs an ADR first (rule D1). Layer and import rules are in `project-structure.md`, routes in `routes-convention.md`, the REST contract in `api-rest.md`.

## Async and blocking work
1. Handlers, services and jobs are `async def`; the data layer is SQLAlchemy 2 async over asyncpg (ADR-0004). No blocking call in a coroutine.
2. Argon2 hashing and checks go through `app/core/hashing.py` (`hash_secret`, `verify_secret`), which runs them in a thread (ADR-0028). Never call a hashing library directly from a route or service. A sign-in code and a password are Argon2id; refresh and reset tokens stay sha256 (`hash_token`, ADR-0008 and the last bullet of ADR-0028, rule P5).
3. A route that checks an Argon2 hash after reading holds no pooled connection while it runs: it ends its read transaction first (RUNBOOK "Sign-in code (OTP)", ENDPOINTS.md `verifyOtp` and `changePassword`). Sign-up and OTP issue hash before their first query instead.

## Sessions, transactions and services
4. A service is a class over an `AsyncSession`, or over other services and `core` seams (ADR-0021, ADR-0027). It may `flush` and open a savepoint (`begin_nested`, as `AccountProfileService` and `PasswordAuthService` do to turn a unique-index race into a 409); it never commits or rolls back the transaction. The route owns `await session.commit()`; a route never uses `session.begin()`; a test or seed may (ADR-0021).
5. A service takes no framework object: no request, response, headers or `Depends` (ADR-0011, ADR-0003).
6. A database error raised by a service you use propagates; do not swallow it, because that leaves the caller's transaction aborted without telling it (ADR-0027, rule D5).
7. A failure the caller must not ignore is an exception: an `AppError` subclass when the client should see it, a plain `RuntimeError` subclass when it is a server fault. Never a `None` that means "failed" (ADR-0021, rule D5).
8. Ownership of a record is checked inside the service, after authentication and role (rule P7, ADR-0022).

## Models and the database
9. Table and column names follow the Prisma schema, quoted (`"Account"`, `"createdAt"`); Python attributes are snake_case and relationships are snake_case, plural for a collection (ADR-0004, ADR-0016).
10. Column mixins are opt-in: `IdMixin`, `TimestampMixin`, `SoftDeleteMixin` from `app/core/db.py`; a table takes the ones its Prisma model has. Timestamps are naive UTC (ADR-0014).
11. Domain tables are soft-deleted: no hard `DELETE` against them (rule P6).
12. A schema change is a new hand-written Alembic revision in `migrations/versions/`, which imports nothing from `app`; an applied revision is never edited; run `uv run alembic check` after a model change (ADR-0017, `project-structure.md` rule 9).
13. The engine hides statement parameters from error text (`hide_parameters`), so a failed query cannot leak a password or token into a log or a 500 (rules D8, P4).

## Settings
14. Settings are `Settings` in `app/config.py`, built once at boot by `get_settings()`; `create_app` keeps them in `app.state.settings` and a route or dependency reads them through `Depends(app_settings)`, so a test that builds `create_app(Settings(...))` is obeyed (RUNBOOK "HTTP tests"). A new setting goes in `Settings`, with its line in `.env.example` and `.env.development.example` (ADR-0010, ARCHITECTURE, `python-core.md` rule 8). `app/` reads no environment variable outside `Settings` today; keep it so.
15. No secret, token, password, date of birth or phone number in a log line (rules D8, P4); the JSON logger redacts on a best-effort basis, which is a net, not permission. What a response may carry is in `api-rest.md` rule 5.

## Background jobs
16. A job is an arq function in `app/workers/`; the API hands it over through the `QueueClient` protocol of `app/core/queue.py`, injected through `get_queue` (ADR-0005, ADR-0024). Arguments are JSON values (never pickle). A job is idempotent (scope task 6.2) and the worker's `MAX_TRIES` is 3 (`app/worker.py`); retries are ours, raised as `Retry(defer=retry_delay(job_try))` (`app/worker.py` comment, ADR-0005).
17. Enqueue after the commit, so a job never runs for data that was rolled back (decided per route in tasks 7.1 and 7.6: RUNBOOK, ARCHITECTURE). `ArqQueueClient.enqueue` raises `QueueUnavailableError` when Redis is down; `NotifierService` logs that one error and lets any other queue or database error propagate (RUNBOOK "Redis, the queue and the worker"), so enqueue through the notifier, or handle `QueueUnavailableError` yourself.

## Errors
18. When the client should see a failure, raise a domain exception from `app/core/errors.py` (a server fault is rule 7's `RuntimeError` subclass); the handlers there turn it into the one error body (ADR-0003, `docs/api/ERRORS.md` "Adding an error", `api-rest.md`).
