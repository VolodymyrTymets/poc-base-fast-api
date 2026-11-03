# ADR-0021 — A service is a class over an `AsyncSession`; the caller owns the transaction

- **Date:** 2026-11-03
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-5.2
- **Supersedes:** nothing. It adds to ADR-0011, which says only what a service may import.

## Context
Task 5.2 writes the first service (`AccountRoleService`); 5.3, 5.4, 7.x and 8.x follow. Without a stated shape each would pick its own, and the
question that matters most, who commits, would be answered differently per file. `get_session` (task 2.1) never commits by itself.

## Decision
- A service is a class built with an `AsyncSession`: `AccountRoleService(session)`. It receives no framework object (ADR-0011).
- A service method may `flush` (to get ids and surface constraint errors) and never commits or rolls back. The caller owns the transaction: a route
  handler ends with `await session.commit()` (`get_session` never commits; it only closes, which rolls back), a test or seed uses `session.begin()`.
  Two services on one session therefore share one transaction.
- A route handler never uses `session.begin()`: a dependency (`require_roles`) may already have read on the request's session, which starts
  its transaction, and `begin()` would then fail with "A transaction is already begun".
- `dependencies` may import model enums such as `AccountRoleType` (an extension of ADR-0011 rule 4, which lists services, core and config); it
  imports no model class to query with.
- A failure the caller must not ignore is an exception: an `AppError` subclass when the client should see it (`core/errors.py`), a plain
  `RuntimeError` subclass named for the case when it is a server fault (it reaches the 500 handler). Never a `None` that means "failed" (rule D5).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Module-level functions taking a session | no place to hold a second collaborator (the cache of 9.2, the queue of 6.1) without changing every call |
| A service that commits | two calls in one request (task 5.3 creates an account, its identity and a role link) could not be one transaction |
| A repository layer under the service | a new layer needs its own ADR and the base is small; the models already are the data access |

## Consequences
- Positive: one transaction per request; services are testable with `db_session` and no HTTP.
- Accepted cost: a caller that forgets to commit loses the write; each route's test must prove the write is visible.

## Revisit when
A service needs more than one session (for example a read replica).
