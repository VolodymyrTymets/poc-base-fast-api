# ADR-0006 — Real PostgreSQL in tests through testcontainers

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.1
- **Supersedes:** none. It replaces the PGlite convention in the Node repo's `CLAUDE.md` (rule P5), which has no Node ADR number. Decision D8 of the scope doc.

## Context
The Node base tests against PGlite, an in-process Postgres with PostGIS, through a `TestDatabase` and a cached migrated
template. PGlite has no Python driver. The test base is goal 3 of this product, and rule P8 forbids a mocked database.

## Decision
- Tests run against a real PostgreSQL with PostGIS: the `postgis/postgis:16-3.4` image, started once per test session with testcontainers.
- One template database is built per run (`alembic upgrade head` plus the seeds); each test module gets a fresh database from it with `CREATE DATABASE ... TEMPLATE`.
- `TEST_DATABASE_URL` points the suite at an existing Postgres instead of Docker.
- Tests need Docker unless `TEST_DATABASE_URL` is set. This is stated in the runbook when the suite lands.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| PGlite | no Python driver |
| SQLite | different SQL dialect, no PostGIS, hides migration bugs |
| Mocked sessions or repositories | violates rule P8; proves nothing about queries |

## Consequences
- Positive: tests exercise the same engine and migrations as production.
- Accepted cost: Docker is required locally and in CI; the first run is slower than PGlite.
- Follow-ups: tasks 3.1 to 3.3.

## Revisit when
A Python-native embedded Postgres with PostGIS becomes available, or Docker cannot be assumed.
