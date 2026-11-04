# ADR-0027 — A service may be built from other services and core seams instead of a session

- **Date:** 2026-11-04
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-6.3
- **Supersedes:** nothing. It extends ADR-0021 (service shape and transactions) and ADR-0025 (one provider per service).

## Context
ADR-0021 says "a service is a class built with an `AsyncSession`". `NotifierService` (task 6.3) writes nothing to the database. It reads a profile, which
`AccountProfileService` already does, and hands a job to a `QueueClient`. Giving it a session only to pass it on would make a second reader of the profile table.

## Decision
- A service may be built from other services and from `core` seams (such as `QueueClient`) and take no session of its own: `NotifierService(profiles, queue)`.
- Its provider in `app/dependencies.py` depends on the providers of what it takes, as `get_account_profile_service` does on `get_file_assert_service` (ADR-0025),
  so a test can replace either.
- The transaction rules of ADR-0021 do not change: such a service never commits, and the caller owns the transaction. A database error raised by a service
  it uses propagates; a service of this kind must not swallow it, because that would leave the caller's transaction aborted without telling it.
- A service that writes through its own queries still takes the session (ADR-0021).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `NotifierService(session, queue)` querying `AccountProfile` itself | a second reader of the profile, and a second place for the "live profile" rule (`deleted` flags) |
| A notifier function in `core/` | it needs a service (`AccountProfileService`), and `core` imports no layer (ADR-0011) |

## Consequences
- Positive: no duplicated query; the notifier is tested on the real profile service and a recording queue.
- Accepted cost: the notifier's reads share the request's session only through `AccountProfileService`.

## Revisit when
A service built this way needs to write: it then takes the session as ADR-0021 says.
