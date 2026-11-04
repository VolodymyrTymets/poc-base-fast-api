# POC-I.9 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-04 (approved in session, recorded by Claude at their instruction; covers creating .claude/rules/routes-convention.md; providers stay in app/dependencies.py)

Note for the approver: approving also confirms creating `.claude/rules/routes-convention.md` (an ask-first path; the ticket wrote `routs-convention.md`).

Pattern followed: `get_queue` and `app_settings` in `app/dependencies.py` (a provider that hands a collaborator to a route and that tests override through
`dependency_overrides`, see `docs/RUNBOOK.md` "HTTP tests"). Services stay as in ADR-0021 (class over a session, never commit). The ADR extends 0021; it is not a second pattern.

## Contract changes
- boundary: none. Internal refactor; `openapi.json` must stay byte-identical (checked, not regenerated). Providers are not routes, so no OpenAPI parameter appears.
- data: none. generated output: none.

## Requirements (ordered; branch `chore/POC-I.9-service-providers`, one commit each)

### R1 — Providers and `require_roles` (S)
- files: `app/dependencies.py` (change): `get_file_assert_service(session, settings)`, `get_account_service(session)`, `get_account_role_service(session)`,
  `get_account_profile_service(session, file_assert)`; each `Depends(get_session)` / `Depends(app_settings)` / the other provider, return type is the service class.
  `require_roles` guard: `claims` first, then `Annotated[AccountRoleService, Depends(get_account_role_service)]` instead of the session.
  Update the module docstring (tasks list).
- layer: `dependencies` (may import `services`, `core`, `config`; ADR-0011 rule 4).
- test: `tests/e2e/test_http_service_providers.py` (new, real Postgres, P8, `asgi_app` + `db_engine`), through the real providers and no private attribute: (a) AC3: a stub route takes
  `get_account_profile_service` and `get_session`, has the service write, commits; the row is read back on a separate connection (`db_engine`), so one shared session is proved by behaviour;
  (b) AC4: `dependency_overrides[get_account_role_service]` returns a fake with no roles and a `require_roles` stub route answers 403; (c) AC4 on a real route:
  `dependency_overrides[get_account_service]` returns a fake and `GET /account` returns its account. Existing `tests/unit/test_require_roles.py`, `tests/e2e/test_http_require_roles.py`,
  `test_http_account.py` (incl. 401 with no database) and `test_http_account_profile.py` must pass unchanged.
- executed how: `uv run pytest tests/e2e/test_http_service_providers.py tests/e2e/test_http_require_roles.py tests/unit/test_require_roles.py`.
- risk: none known; FastAPI's per-request cache of `get_session` is what (a) proves.

### R2 — Routes use the providers (S)
- files: `app/routers/account.py` (`AccountService` via `get_account_service`, keeps `session` only if it needs the commit: it does not, so drop `get_session`),
  `app/routers/account_profile.py` (`AccountProfileService` via `get_account_profile_service`; keep `session: Depends(get_session)` for the commit; drop `settings`, `FileAssertService` imports).
- layer: routers.
- test: `tests/e2e/test_http_account.py`, `tests/e2e/test_http_account_profile.py` untouched and green (they prove behaviour is the same, including the commit and 401-without-database).
  New `tests/unit/test_routers_use_service_providers.py` (AC6): parses each `app/routers/*.py` with `ast`; fails on a call whose callee name ends in `Service`.
- executed how: start `uv run poc-base-fast-api` with a migrated PostGIS DB, mint a token with `issue_token` and local JWT secrets (sign-in comes with 7.3), `curl GET /api/v1/account` and `PATCH .../profile`; paste request and response.
  Then `uv run python -m app.cli --export-openapi --check` (exit 0).
- risk: removing `get_session` from `read_account` could change dependency order (401 with no DB); the existing no-database 401 test covers it.

### R3 — ADR, rule and docs (S)
- files: `docs/decisions/ADR-0025-service-providers.md` (new: decision = one provider per service in `app/dependencies.py`, takes `get_session` so a request shares one session, a provider
  that needs another service depends on its provider, the route owns the commit, a router never constructs a service, tests swap through `dependency_overrides`; alternatives: a `ServiceContainer`/class-based
  provider, `Depends(XService)` directly on the class — rejected because the class takes plain constructor args such as another service and settings);
  `.claude/rules/routes-convention.md` (new, `paths: app/routers/**`, `app/dependencies.py`; the same rules as short numbered lines, plus the guard order: authenticate, role, then the service checks ownership);
  `.claude/rules/project-structure.md` (rule 4/5: routers use providers from `dependencies`; add the providers to the `dependencies.py` line);
  `docs/ARCHITECTURE.md` (the `dependencies.py` row, the Decided list: ADR-0025); `docs/features/POC-I.9/spec.md` ticked.
- layer: docs and rules only.
- test: AC6's unit test is the enforcement; `uv run ruff check .`, `format --check`, `mypy`, `pytest tests/unit` all green.
- executed how: n/a for docs; link check by reading the ADR numbers against `docs/decisions/`.
- risk: `.claude/**` is ask-first (protected-paths); approval of this plan is the confirmation for the two rule files.

## Docs to update in this PR
- [ ] docs/features/POC-I.9/spec.md (criteria checked off)
- [ ] docs/ARCHITECTURE.md — dependencies row, Decided list
- [ ] docs/DOMAIN_GLOSSARY.md — none (no new domain term)
- [ ] docs/decisions/ADR-0025 — new, extends ADR-0021
- [ ] docs/RUNBOOK.md "HTTP tests" — one line: override a service with `dependency_overrides[get_x_service]`

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A provider breaks the one-session-per-request guarantee | a flushed write is not committed, silent data loss | R1's same-session test, written first |
| Import cycle `dependencies` <-> `services` | boot fails | `uv run python -c "import app.main"` after R1; services import nothing from `dependencies` today |
| `openapi.json` drifts | stale-spec test red | `--export-openapi --check` after R2 |

## Assumptions
- "All routes" = the two existing routes plus the `require_roles` guard; `/health` has no service. Package 7 routes follow the rule when built.
- The rule file is `.claude/rules/routes-convention.md` (the ticket's `routs-convention.md` read as a typo).
- Complexity: R1 S, R2 S, R3 S. No new runtime dependency.
