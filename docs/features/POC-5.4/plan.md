# POC-5.4 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-03 (approved in session, recorded by Claude at their instruction)

Pattern followed: services `app/services/account.py` and `file_assert.py` (ADR-0021: class over a session, flush never commit, domain errors as exceptions);
the route `app/routers/account.py` (the handler owns the commit, `get_session`); the guard `require_roles` of `app/dependencies.py` (task 5.2), first used by a real route here;
HTTP tests `tests/e2e/test_http_account.py` (app with JWT secrets, rows committed through `db_engine`, `token_for`). No new pattern, no ADR.

## Contract changes
- boundary: new `PATCH /api/v1/accounts/{accountId}/profile`; `openapi.json` regenerated with `uv run python -m app.cli --export-openapi`.
- data: none (updates `AccountProfile`; no migration). config / dependencies: none.

## Requirements (ordered; branch `feat/POC-5.4-profile-update`, one draft PR, one commit each)

### R1 — AccountProfileService (M)
- files: `app/services/account_profile.py`: `AccountProfileService(session, file_assert: FileAssertService)`;
  `get_by_account_id(account_id) -> AccountProfile | None` (live profile of a live account); `update(caller_id, account_id, changes: UpdateAccountProfileInput) -> AccountProfile`:
  first statement, before any query, `ForbiddenError` when `caller_id != account_id` (the ownership layer of rule P7 lives in the service, so any caller of `update` gets it);
  load the profile (`NotFoundError` if none); if `avatar_id` was sent and is not `None`, `file_assert.get_owned_file(avatar_id, account_id)` (raises `ForbiddenError`);
  apply only `changes.model_fields_set` (explicit `None` clears, except `email`, which the model already refuses); flush inside `session.begin_nested()` so a unique violation on
  `AccountProfile_email_key` becomes `EmailAlreadyRegisteredError` and leaves the session usable; any other `IntegrityError` is re-raised. Never commits.
- layer: services (imports `app.models`, `app.schemas`, `app.core`, `app.services.file_assert`; no FastAPI).
- test: `tests/e2e/test_db_account_profile_service.py` on `db_session` (real Postgres, P8): a different `caller_id` → `ForbiddenError` with nothing read or written (the profile and the avatar file are untouched); update fields; partial update keeps the rest; explicit `None` clears the avatar and a name;
  `{}` changes nothing; email already normalised by the model, stored as given; another account's email → `EmailAlreadyRegisteredError` and a query still works after; own email again → ok;
  avatar owned / not owned / unknown / soft-deleted; an email held by a soft-deleted account (and by an account with a soft-deleted profile) still → `EmailAlreadyRegisteredError`; no profile, soft-deleted profile, soft-deleted account → `NotFoundError`; `get_by_account_id` live and `None`.
- executed how: the e2e run on the PostGIS container.
- risk: how asyncpg exposes the violated constraint through SQLAlchemy's `IntegrityError` (`exc.orig`, `__cause__.constraint_name`); cheapest check: the duplicate-email test with
  the constraint-name assertion written first. If it cannot be read, fall back to a pre-check query plus the unique index as the race guard.

### R2 — The PATCH route (M)
- files: `app/routers/account_profile.py`: `PATCH /{account_id}/profile` (prefix `/accounts`), `response_model=AccountProfileResponse`, dependencies
  `Depends(require_roles(ADMIN, CUSTOMER))` (claims), `get_session` and `Depends(app_settings)`; the handler builds `AccountProfileService(session, FileAssertService(session, settings))`; call `service.update(claims.account_id, account_id, body)` and nothing else of its own; `await session.commit()`
  (ADR-0021); return `AccountProfileResponse.model_validate(profile)`. `openapi.json` (generated).
- layer: router (parses, calls the service, commits, returns a schema; no rule: project-structure rule 5).
- test: `tests/e2e/test_http_account_profile.py` (app built with JWT secrets, accounts committed through `db_engine`): AC1 to AC9 over HTTP: 401 without a token, 403 for another account's id and
  for a role-less account, 404 with no profile, 200 update then `GET /api/v1/account` shows it, 409 for a duplicate (mixed case) with the profile unchanged, 403 for an avatar of another account,
  422 for `SSN`/`is18YearOld` and for `email: null`; two tests that pin the Q1 behaviour: a token of an unknown account is 403 (from `require_roles`) and a soft-deleted account that still holds a role link is 404; `tests/unit/test_openapi_stale.py` and `test_response_models.py` run as they are.
- executed how (evidence): scratch PostGIS on a free port, `alembic upgrade head`, a scratch script under the scratchpad (not in the repo) creates two accounts with `AccountService.create_password_account` (two distinct emails, placeholder hash and salt), commits one `File` row with `created_by_id` set to the second account (no upload route exists before 8.2) and mints tokens; then `uv run poc-base-fast-api` (secrets and `DATABASE_URL` exported,
  never in `.env`); call the PATCH with an HTTP client as the owner, with another account's id, without a token, with a duplicate email, with a foreign avatar id and with `SSN`; paste the responses.
- risk: `require_roles` and the route share one session through `get_session` (FastAPI caches the dependency per request); the first test that reads then writes on it proves it.

## Node spec port (`account-profile.service.spec.ts`, 10 cases; `update-account-profile.e2e-spec.ts`, 4 active cases)
| Node case | Here |
|-----------|------|
| should be defined | does not apply |
| update fields and return the updated profile | service test + AC1 over HTTP |
| partial update preserves unchanged fields | service test (AC2) |
| throws when the accountId does not exist | `NotFoundError` service test (AC4); over HTTP another id is 403 (AC3) |
| getAccountProfileById: existing, null, without `info` | `get_by_account_id` live and `None`; the `info` case does not apply (no GraphQL) |
| email stored trimmed and lowercased | the model lowercases (task 4.3; a value with spaces is 422 in this base, ENDPOINTS rule); HTTP test sends mixed case |
| rejects an email another account has, ignoring case | service and HTTP tests (AC6) |
| leaves the email alone when not included | service test (AC2) |
| e2e: not authenticated | 401 test |
| e2e: profile does not exist (really the 403 for another id) | 403 and 404 tests |
| e2e: update account profile | AC1 and AC8 |
| e2e: only the own profile | 403 test (AC3) |
New here: avatar ownership (Node's e2e for it is commented out), 409 on a duplicate at the HTTP level, the role-less 403, the soft-delete cases.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e`, `uv run python -m app.cli --export-openapi --check`.
All ported cases pass. Anything not run goes under "Not verified".

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-5.4/spec.md (ACs checked off)
- [ ] docs/ARCHITECTURE.md: `services/account_profile.py` and the PATCH route built; the route count sentence; the data-truth paragraph (the profile is updated)
- [ ] docs/api/ENDPOINTS.md: the `updateAccountProfile` row marked built; note the 404 for a deleted account and that the cache hook waits for 9.2
- [ ] docs/DOMAIN_GLOSSARY.md: no new term; docs/decisions: none

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Constraint name not readable from the driver error | a non-email unique error mapped to 409 | R1 test written first; fallback in R1 |
| A soft-deleted account with a role link edits a profile | edits on a deleted account | AC4 makes it 404; the uniform 401 is a separate change (Q1) |
| Email change without re-authentication | account takeover path carried from Node | out of scope, issue I.8; stated in the PR |

## Estimate
R1 M, R2 M.

## Assumptions
Q1 to Q3 of the spec. The caller (route) owns the transaction. Empty body is a no-op 200.

## Not covered
Cache invalidation, profile read route, avatar upload, re-authentication for an email change, deleted-account 401 on guarded routes.
