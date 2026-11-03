# POC-5.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr 2026-11-03

Pattern followed: `app/dependencies.py` `current_account` (a dependency on `app_settings`) and `app/core/db.py` `get_session` for the session;
`app/seeds/items/init_roles.py` for querying `AccountRole` with `AsyncSession` and the `app.models` imports; tests follow
`tests/e2e/test_http_auth_dependencies.py` (test-local routes added to `create_app`) plus `db_session` of `tests/conftest.py`. The
service is a class taking an `AsyncSession`: no Python service exists yet (the files are docstring-only), so this sets the shape 5.3/5.4 copy;
ADR-0011 says only what a service may import, so the shape is recorded in a new ADR-0021 (R1).

## Contract changes
- boundary: none. No route uses the guard yet; `openapi.json` should not change (stale test confirms). 403 body is the existing `FORBIDDEN`.
- data: none (reads `AccountRole`/`AccountOnRole`, writes one `AccountOnRole` row on request).
- config / dependencies: none; no new runtime dependency.

## Requirements (ordered; branch `feat/POC-5.2-role-guard`, one draft PR, one commit each)

### R1 — AccountRoleService (M)
- files: `docs/decisions/ADR-0021-service-shape-and-transactions.md` (new: a service is a class built with an `AsyncSession`, flushes and never commits, the caller (route via `get_session`, or test) owns the transaction, domain errors are exceptions); `app/services/account_role.py` (change from docstring: `AccountRoleService(session)`, `get_account_roles(account_id) -> list[AccountRoleType]`
  with a join on `AccountOnRole` and `AccountRole` filtering both `deleted` flags; `add_account_to_role(account_id, role_type) -> AccountOnRole`
  looking the role up by type, flushing, never committing; `RoleNotFoundError(RuntimeError)` naming the type only).
- layer: services (imports `app.models`, `app.core`; no FastAPI).
- test: `tests/e2e/test_db_account_role_service.py` on `db_session` (real Postgres, rule P8; seeded roles from the template): roles of an
  account with none / one / two; soft-deleted link and soft-deleted role excluded; add then get; unknown type raises; duplicate add raises
  `IntegrityError`. Ports the Node spec's only case ("is defined") and goes beyond it.
- executed how: the e2e run itself against the PostGIS container; plus `uv run python -c` is not needed (no entrypoint).
- risk: the `SoftDeleteMixin` column is named `deleted`; confirm with `app/core/db.py` before writing the query.

### R2 — require_roles dependency (M)
- files: `app/dependencies.py` (change: `require_roles(*roles: AccountRoleType)` returns an async dependency that depends on `current_account` and
  `get_session`, calls the service, raises `ForbiddenError` when the intersection is empty, returns the `TokenClaims`; empty `roles` raises
  `ValueError` at call time; update the module docstring).
- layer: dependencies.
- test: `tests/e2e/test_http_require_roles.py`: test-local routes `require_roles(ADMIN)` and `require_roles(ADMIN, CUSTOMER)` on an app built as in
  `test_http_auth_dependencies.py`: `create_app(Settings(database_url=module_database_url, jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY))` (`utils.jwt`; the
  stock `asgi_app` has no JWT secrets), run through `running_client`. Accounts and role links are inserted and committed through `db_engine` (not
  `db_session`: its outer transaction is rolled back and the request session would not see the rows), with unique ids per test because commits stay for the module; tokens from `issue_token`; AC1 to AC4, 403 body shape; AC7 as a unit test in
  `tests/unit/test_require_roles.py` (no database).
- executed how (evidence): scratchpad script with its own `CREATE DATABASE` scratch database (`DATABASE_URL` exported explicitly, never the `.env` one), `alembic upgrade head`,
  one throwaway `JWT_SECRET`/`JWT_REFRESH_TOKEN_SECRET` pair shared by the server and the token minting; the script creates three accounts through the R1 service plus a
  commit and serves the guarded route with `uvicorn`; `curl -i` as admin, customer, roleless account and with no token; expected 200, 403, 403, 401; paste the responses.
- risk: none; ADR-0011 rule 4 (`.claude/rules/project-structure.md`) lets `dependencies` use `services`.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker or
`TEST_DATABASE_URL`), `uv run python -m app.cli --export-openapi --check`. Anything not run goes under "Not verified".

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-5.2/spec.md (ACs checked off)
- [ ] docs/ARCHITECTURE.md: `services/account_role.py` and `require_roles` built; the layout row no longer calls `services/` docstring-only; the sentence "Only the seed runner writes to a database so far" is reworded (the service writes `AccountOnRole`); ADR-0021 added to the Decided list
- [ ] docs/api/ENDPOINTS.md: the Token checks bullet gains the role layer (403 `FORBIDDEN`, deleted links not counted)
- [ ] docs/DOMAIN_GLOSSARY.md: no new term
- [ ] docs/decisions/ADR-0021-service-shape-and-transactions.md (R1)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Filtering soft-deleted links differs from Node | a fork migrating data sees fewer roles | stated in the spec; it is rule P6 |
| A guard that checks roles but not that the account exists | a deleted account with a live role link passes | closed by 5.3; noted in the PR "Not covered" |

## Estimate
R1 M, R2 M.

## Assumptions
Q1 to Q3 of the spec. The caller owns the transaction. Fail closed on an empty role list.

## Not covered
Real routes, ownership checks, deleted-account rejection, role caching, role management endpoints.
