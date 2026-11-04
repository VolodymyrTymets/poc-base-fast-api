---
description: How a route gets its services and who owns the transaction - one Depends provider per service in app/dependencies.py (ADR-0025, extends ADR-0021).
paths:
  - "app/routers/**"
  - "app/dependencies.py"
  - "tests/e2e/test_http_*.py"
---

# Routes convention

Decided in ADR-0025 and ADR-0021. If they disagree with this file, the ADR wins and you raise it.

1. A route never constructs a service. It takes `service: Annotated[XService, Depends(get_x_service)]`. `tests/unit/test_routers_use_service_providers.py` enforces it.
2. A new service gets its provider in `app/dependencies.py` in the same PR: `get_<service>_service(session=Depends(get_session), ...)`. A service that needs another service depends on that service's provider.
3. A route that writes ends with `await session.commit()` on the `session` from `Depends(get_session)`: it is the same session the providers used (cached per request). A route never uses `session.begin()` (ADR-0021).
4. Guard order on a protected route is authenticate, then role (`require_roles`), then the per-record ownership check inside the service (rule P7). List the claims dependency before the service and session, so a bad token is a 401 even with no database.
5. A route parses the request, calls a service and returns a response schema. No business logic, no ORM object in a response (`project-structure.md`).
6. A test that must replace a service sets `app.dependency_overrides[get_x_service]`; it does not patch the class. Do it for a service that fronts an external edge, or to test the wiring; never to fake the data layer: that is tested on a real Postgres (rule P8, `testing-python.md`).
