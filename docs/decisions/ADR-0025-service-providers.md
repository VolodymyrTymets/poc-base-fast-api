# ADR-0025 — One `Depends` provider per service, in `app/dependencies.py`

- **Date:** 2026-11-04
- **Status:** accepted; extended by [ADR-0027](ADR-0027-service-built-from-services.md) (a provider may depend on other providers)
- **Deciders:** volodymyr
- **Ticket:** POC-I.9
- **Supersedes:** nothing. It extends ADR-0021 (service shape and transactions) and ADR-0011 (what `dependencies` may import).

## Context
Routes built their services by hand (`AccountProfileService(session, FileAssertService(session, settings))`), so every route repeated the wiring and a test could not
swap a service through `dependency_overrides`. Package 7 adds six auth routes; they should start on providers.

## Decision
- Every service has a provider in `app/dependencies.py`, named `get_<service>_service`, that takes `get_session` (and `app_settings` where the service needs settings) and returns the class.
  `get_session` is cached per request, so the guard, the service and the route's own `session` are one `AsyncSession`.
- A provider whose service needs another service depends on that provider (`get_account_profile_service` on `get_file_assert_service`), so a test may replace either.
- A route takes `Annotated[XService, Depends(get_x_service)]` and never constructs a service. It still owns the commit (ADR-0021): it also takes `session` from `get_session` when it writes.
- `require_roles` loads roles through `get_account_role_service`.
- A test swaps a service with `app.dependency_overrides[get_x_service]`.
- `tests/unit/test_routers_use_service_providers.py` fails when a router module constructs a `...Service`.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Providers and `XServiceDep` aliases in each `services/*.py` | a service would import `Depends`, against ADR-0011 rules 4 and 6 (no framework object in `services`), and `services` would import `dependencies` for the settings, a cycle with `require_roles` |
| `Depends(XService)` on the class itself | the constructor takes an `AsyncSession`, another service and settings, which FastAPI cannot read as request fields (it fails when the route is defined) |
| A container object that builds all services | a second wiring mechanism beside `Depends`, and nothing to override per service |

## Consequences
- Positive: one place for the wiring; tests replace a service without a database; the auth routes of package 7 copy no wiring.
- Accepted cost: a new service needs a provider in `dependencies.py`.

## Revisit when
`dependencies.py` grows past what one file holds comfortably; then split it by module, keeping the names.
