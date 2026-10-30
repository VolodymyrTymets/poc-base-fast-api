# POC-2.1 — Async engine, request-scoped session, declarative Base and mixins

Scope-doc row 2.1 (3 h). Depends on 1.5 (merged). The ticket text: "Async engine (asyncpg), session per request as a FastAPI
dependency, declarative `Base`; mixins for uuid4 `id`, `createdAt`, `updatedAt`, `deleted` (P2). Quoted Prisma table/column
names (`"Account"`, `"createdAt"`)". Acceptance in the doc: "Smoke test opens a session and runs `SELECT 1`".

## Problem
No database access exists. Tasks 2.2 to 2.5, 3.1 and every service after them need one shared engine, one way to get a session,
and one `Base` whose metadata carries the Prisma-compatible naming, so the models are written once and Alembic (2.4) can diff them.

## Goal / business value
Goal 1 (scaffolding): a fork gets the data layer plumbing without rebuilding it. Goal 3 (test base) needs a session that tests
can point at a real Postgres (rule P8). Non-negotiable 4 (soft deletes only) gets a mixin instead of a convention.

## Scope
- in: `app/core/db.py` (engine and session-factory builders, the `get_session` dependency, `Base`, the naming convention, the
  three mixins); ADR-0014 (supersedes one bullet of ADR-0004); a `DATABASE_URL` setting; engine creation and disposal in the app
  lifespan; a smoke test against a real Postgres; two runtime dependencies, `sqlalchemy[asyncio]` and `asyncpg` (rule C2,
  approved by the human); docs.
- **out (explicit):** any model or table (2.2, 2.3); Alembic (2.4); test-database fixtures, templates and testcontainers (3.1);
  schema parity with Prisma (2.5); transactions policy inside services (5.3 decides per use case); read cache (9.x);
  connection-pool tuning beyond SQLAlchemy defaults.

## Acceptance criteria
- [ ] AC1 Given a reachable Postgres and `DATABASE_URL`, when a session from `get_session` runs `SELECT 1`, then it returns 1 (the scope-doc criterion).
- [ ] AC2 Given two requests to a route that depends on `get_session`, then each gets its own session, and the session is closed when the response is done.
- [ ] AC3 Given `DATABASE_URL` is unset, then the app still boots and `GET /api/v1/health` answers 200 (no database is touched at boot), and a route that needs a session raises a `RuntimeError` naming `DATABASE_URL` (visible in the server log), not an `AttributeError`; the client gets a generic 500 that does not name the setting (the `{"error": {...}}` envelope is task 4.2).
- [ ] AC4 Given SIGTERM or app shutdown, then the engine is disposed in the lifespan shutdown.
- [ ] AC5 Given a model built from `Base`, then its constraint and index names follow the Prisma shape (`<Table>_pkey`, `<Table>_<cols>_key`, `<Table>_<cols>_idx`, `<Table>_<col>_fkey`), and a mixed-case table or column name is emitted quoted.
- [ ] AC6 Given the opt-in mixins (ADR-0014, Q2): `IdMixin` adds a `text` primary key `id` with a client-side uuid4 string; `TimestampMixin` adds `createdAt` (`timestamp(3)`, not null, default now) and an `updatedAt` that is nullable in the database but set by the application on insert and on every update (Prisma's `@updatedAt` behaviour); `SoftDeleteMixin` adds `deleted` (not null, default false). Each works alone, and a table uses only the ones its Prisma model has.
- [ ] AC7 Given a malformed `DATABASE_URL` (wrong scheme), boot fails naming the field, and the URL, including any password in it, appears nowhere in the error text.
- [ ] AC8 Docs match: ARCHITECTURE, RUNBOOK, ADR-0004 note, env templates.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Handler raises after using the session | session is closed and its open transaction rolled back, nothing is committed; checked from a second connection | test in R2 |
| Database down at boot | app boots; the first query fails; health stays 200 (no ping in health) | AC3, Q3 |
| `postgresql://` URL given without `+asyncpg` | rejected at boot with a message naming the driver | Q4 |
| Client disconnects mid-request | the dependency's `async with` still closes the session | SQLAlchemy context manager |

## Open questions
| # | Question | Assumed answer | Needs a human? |
|---|----------|----------------|----------------|
| Q1 | Add `sqlalchemy[asyncio]` and `asyncpg` as runtime dependencies (C2). ADR-0004 already decides them. | yes; the ADR is the approval, `Approved-by:` confirms | yes (C2) |
| Q2 | Mixins: the scope row asks for mixins for `id`, `createdAt`, `updatedAt`, `deleted`; accepted ADR-0004 says the shared mixin carries only `deleted` and ids/timestamps are per table (several Prisma tables lack some; `Account.updatedAt` is nullable; `AccountOnRole` has a composite key). The gate blocked building the extra mixins without a superseding ADR (P2). | **Decided by the human: option (b).** A new ADR-0014 supersedes that ADR-0004 bullet with three opt-in mixins; `updatedAt` is nullable and `id` is `text` because that is what Prisma emits. | decided |
| Q3 | Does `/health` ping the database? | No, it stays a liveness check (ADR-0003 scope); a readiness check is not in the plan. | confirm |
| Q4 | `DATABASE_URL` default and validation. | No default (`None`); when set it must start with `postgresql+asyncpg://`. The `.env.example` value already has that shape. Validation errors never echo the URL (it holds a password; rules D8, P4). | confirm |
| Q5 | Who commits? | The session only opens and closes; services call `commit()` explicitly (5.3 needs "one transaction"), no autocommit in the dependency. | confirm |
| Q6 | The smoke test needs a real Postgres (P8) and Docker is not running here; a Postgres is listening on `localhost:5432`. Without `TEST_DATABASE_URL` the test must fail with a clear message, not `skip` (B3). Is a failing `pytest tests/e2e` on a machine with no database acceptable until 3.1 adds testcontainers? | Yes; it reads `TEST_DATABASE_URL`, fails loudly when unset, and the runbook says so. | yes |
