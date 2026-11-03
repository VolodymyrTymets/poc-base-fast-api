# POC-5.5 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-03 (approved in session, recorded by Claude at their instruction)

Pattern followed: `app/seeds/items/init_roles.py` (a class with `name`, `needs_to_run(session)`, `run(session)`; the runner owns the transaction and the history row)
and `app/seeds/registry.py` (`base_items`, `development_items`). The Node originals are `api/src/migrations/items/init.admin.migration.ts` and
`items.development/init.customer.migration.ts`. The profile fields are written through `AccountProfileService.update` (task 5.4), accounts through `AccountService` (5.3) and
`AccountRoleService` (5.2). Tests follow `tests/e2e/test_db_seed_init_roles.py` (`unseeded_session_factory`, `run_seeds`) and `tests/unit/test_seed_registry.py`. One structural change, recorded in ADR-0023 (R1): `seeds` may import `schemas`.

## Contract changes
- boundary: none (no route); `openapi.json` must not change. data: rows only, no migration. config / dependencies: none. The registry already receives `Settings`, which the items need for `FileAssertService`.

## Requirements (ordered; branch `feat/POC-5.5-admin-customer-seeds`, one draft PR, one commit each)

### R1 — init.admin (M)
- files: `app/seeds/items/init_admin.py`: constant `ADMINS` (one entry: phone `+12125550100`, first name `Admin`, last name `User`); `InitAdmin(settings)` with `name = "init.admin"`;
  `needs_to_run`: no live account holds a live `ADMIN` link, by joining `AccountOnRole` to `AccountRole` and comparing `AccountRole.type` (never a role id with a string, issue I.4);
  `run`: per entry, following `AccountService._create` (`app/services/account.py`): `Account(last_login_at=utc_now())`, `account.profile = AccountProfile(phone_number=...)`, `account.identity = None` set explicitly (an unset relationship lazy-loads, which an async session cannot do), `session.add`, flush, then `AccountRoleService.add_account_to_role(account.id, AccountRoleType.ADMIN)` (not `create_customer`, which adds `CUSTOMER`), then
  `AccountProfileService.update(id, id, UpdateAccountProfileInput(firstName, lastName))`. `app/seeds/registry.py`: `base_items()` stays `[InitRoles()]`; `development_items(settings)` returns `[InitAdmin(settings)]` (the customer item joins in R2); `seed_items` passes the settings. The admin is not seeded in production (decided in session).
- the copy of `AccountService._create` stays in the seed item, with a `WHY` comment pointing at it, rather than a new public `create_admin` on the merged 5.3 service (C1: this task touches `app/seeds/` only); a later change to `_create` must revisit it.
- layer: seeds (imports `services`, `models`, `core`, `config`, and `schemas` for `UpdateAccountProfileInput`, allowed by the new ADR-0023).
- ADR: `docs/decisions/ADR-0023-seeds-may-import-schemas.md` (supersedes only the import line of ADR-0011 rule 4, and only for `seeds`; `workers` are not covered, the worker task (6.x) raises its own question if it needs `schemas`). ADR-0011's body is not rewritten: only its Status line gets the note "the `seeds` import line is superseded by ADR-0023", as ADR-0012 did. `.claude/rules/project-structure.md` rule 4 is updated to match in the same commit (an ask-first path: the hook will ask). Decided by the human in session.
- test: `tests/e2e/test_db_seed_init_admin.py` on `unseeded_session_factory` after `InitRoles`: one admin with role `ADMIN` only and the profile names (AC3, AC4); two runs add nothing (AC2); a database that already
  has another admin is left alone; running without the roles fails with `RoleNotFoundError` recorded in `SeedHistory` (AC8). `tests/unit/test_seed_registry.py`: every environment gets `init.roles` first, the development environments also `init.admin`, production only the roles (AC6).
- executed how: `uv run python -m app.seeds` against a scratch PostGIS (migrated), twice; a `psql` count of accounts per role.
- risk: the old registry tests assert the exact lists and a stand-in development item; they are updated to the new lists, not weakened (stated in the PR).

### R2 — init.customer and the registry (M)
- files: `app/seeds/items/init_customer.py`: constant `CUSTOMERS` (three entries in the shape of the Node ones, without `SSN` and `password`, with fictional values in the reserved range, not copied from Node: `+12125550101` John Doe Smith `customer+d1@example.com` `1990-01-01`; `+12125550102` Jane Doe Smith `customer+d2@example.com` `1995-05-05`; `+12125550103` Alice Smith Johnson `customer+d3@example.com` `1985-10-10`; no existing test uses these emails);
  `InitCustomer(settings)` with `name = "init.customer"`; `needs_to_run`: any sample phone has no live account (`AccountService.get_by_phone`); `run`: for each missing phone
  `AccountService.create_customer(phone)` then `AccountProfileService.update(id, id, input)` with the names, email and date of birth. `registry.py`: `development_items(settings)` returns `[InitAdmin(settings), InitCustomer(settings)]`, in that order.
- layer: seeds.
- test: `tests/e2e/test_db_seed_init_customer.py`: a profile already holding `customer+d1@example.com` makes the item fail with `SeedError` and a `SeedHistory` row with `successful = false` (the service raises `EmailAlreadyRegisteredError`; the spec edge case); three customers with `CUSTOMER` only and the profile fields (AC4); one pre-existing sample phone is not duplicated and the other two are created (AC5);
  customers are created although an admin exists (AC5); two runs add nothing (AC2); `tests/e2e/test_db_seed_registry_run.py`: the whole `seed_items(Settings(app_env="local"))` on an unseeded database gives
  2 roles, 1 admin, 3 customers and 3 history rows, and `production` gives the roles only (AC1, AC6); `tests/unit/test_seed_assets.py`: every phone passes `PhoneNumber`, every email `ProfileEmail`,
  phones and emails are distinct, no `SSN` or `password` key exists (AC7); `tests/unit/test_seed_registry.py` updated for the development list.
- executed how (evidence): scratch PostGIS, `alembic upgrade head`, then `uv run poc-base-fast-api` (starts the seeds before serving) with `DATABASE_URL`, `JWT_SECRET` and `JWT_REFRESH_TOKEN_SECRET` exported (throwaway values, never in `.env`; with them unset a token cannot be issued or checked, RUNBOOK "Token secrets"); query the counts with `psql`; stop,
  start the app again and count again (a second boot adds nothing); mint a token for a customer id read with `psql` using `uv run python -c` with `issue_token(settings, <id>, TokenType.ACCESS)`, then `GET /api/v1/account` shows its `profile.email`; paste the request and response.
- risk: the e2e template database is seeded with `seed_items`; if it runs for a development environment, every test module now starts with 4 more accounts. Cheapest check: the full e2e run after R2 (tests that
  count rows must count relatively); if one breaks, fix its count (not the seed) and say so in the PR.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e`, `uv run python -m app.cli --export-openapi --check`, `uv run alembic check` (no schema change).
Anything not run goes under "Not verified".

## Node port (no Node spec exists for either item; the behaviour is read from the two migration files)
| Node behaviour | Here |
|----------------|------|
| `inNeedToRun`: admin count by `roleId: 'ADMIN'` (never matches a uuid, so Node re-ran it on every boot unless the history row stopped it) | by role type through the join (AC3, issue I.4) |
| customer `inNeedToRun`: `account.count() === 0`, which is false once the admin exists, so Node never seeded the customers | per missing phone (AC5); a stated fix |
| admin: account, profile with phone, role, `updateAccountProfile` names | same, through the 5.4 service; last name `User` instead of `Trukkit` (another project's name) |
| customers: `createCustomerAccount(phone)` then `updateAccountProfile` with names, email, date of birth | same; `SSN` dropped (ADR-0015), the unused `password` dropped, phones and emails replaced by fictional ones (555-0100 range, `example.com`) |
| admin phone `+11111111111` | `+12125550100`: the old one fails `phonenumbers`; the new one is in the reserved fictional range (decided in session) |
| admin in the base list (every environment) | development list only (decided in session) |

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-5.5/spec.md (ACs checked off)
- [ ] docs/ARCHITECTURE.md: `app/seeds/` row (the development list is no longer empty; the two items) and the data-truth paragraph; the status line and the "Decided (ADR-0003 to ADR-0021 ...)" heading go to ADR-0023, with bullets for ADR-0022 (self-scoped routes) and ADR-0023 (seeds may import schemas)
- [ ] docs/RUNBOOK.md: "Seeds" section (the admin and the three sample customers, their phones and emails, the OTP-only sign-in; none of them exists in production)
- [ ] docs/DOMAIN_GLOSSARY.md: the seed item row names the admin and the customers
- [ ] docs/decisions/ADR-0023 (R1); the import line of `.claude/rules/project-structure.md` rule 4; the Status line of ADR-0011

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| More rows in the test template | a test that counts all rows breaks | full e2e after R2 |
| A sample admin in production | a known phone with the ADMIN role | avoided: the admin is in the development list only (Q3); the RUNBOOK says so |
| A sample customer email clashes with a fork's data | the item fails and the boot stops | stated in the RUNBOOK; the item is in the development list only |

## Estimate
R1 M, R2 M.

## Assumptions
Q1 decided; Q2 to Q4 of the spec. Items never commit; the runner owns the transaction.

## Not covered
Sign-in routes, password hashes for the sample customers, a configurable admin phone through the environment.
