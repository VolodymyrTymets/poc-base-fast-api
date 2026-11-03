# POC-5.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-03 (approved in session, recorded by Claude at their instruction)

Pattern followed: `app/services/account_role.py` (ADR-0021: class over `AsyncSession`, flush, never commit); `app/dependencies.py` `current_account` and
`get_session` for the route; tests follow `tests/e2e/test_db_account_role_service.py` (service on `db_session`) and `tests/e2e/test_http_require_roles.py`
(app built with JWT secrets, rows committed through `db_engine`, tokens from `issue_token`). Precedent for the router: none yet (all routers are
docstring-only), so this route sets the shape 5.4 copies; no new pattern, no ADR.

## Contract changes
- boundary: new `GET /api/v1/account` and its response models; `openapi.json` regenerated with `uv run python -m app.cli --export-openapi`.
- data: none (no migration; reads and inserts into existing tables).
- config / dependencies: none; no new runtime dependency.

## Requirements (ordered; branch `feat/POC-5.3-account-service`, one draft PR, one commit each)

### R1 — AccountService (M)
- files: `app/services/account.py`: `AccountService(session)`; `get_by_id(account_id) -> Account | None` and `get_by_phone(phone) -> Account | None`
  (`selectinload` of the live profile, `Account.deleted` false, profile filtered on `deleted` false, queries run with `execution_options(populate_existing=True)` so a profile soft-deleted earlier in the same session is not served from the identity map); `create_customer(phone_number) -> Account`;
  `create_password_account(email, hash, salt) -> Account` (email stored as given: the caller normalises, 7.3). Both create the account
  (`last_login_at` = `utc_now()` from `app.core.db`), profile, role link through `AccountRoleService.add_account_to_role(CUSTOMER)` and, for the password one,
  the `AccountIdentity`, then one `flush`.
- layer: services (imports `app.models`, `app.core`, `app.services.account_role`; no FastAPI).
- test: `tests/e2e/test_db_account_service.py` on `db_session` (real Postgres, rule P8): AC5, AC6, AC7 (duplicate email → `IntegrityError`, rollback leaves no rows; phone is not unique, so no phone test),
  profile-less and soft-deleted-profile cases, unknown id and phone → `None`.
- executed how: the e2e run on the PostGIS container (no entrypoint yet).
- risk: `add_account_to_role` flushes by itself, so "one transaction" (no commit) is what the test asserts, not one flush.

### R2 — Response models and GET /api/v1/account (M)
- files: `app/schemas/account_profile.py` (add `AccountProfileResponse`: `id, phoneNumber|null, firstName, lastName, middleName, dataOfBirth, email,
  isPhoneVerified`; camelCase aliases, `from_attributes`); `app/schemas/account.py` (`AccountResponse`: `id, createdAt, updatedAt|null, profile|null`);
  `app/routers/account.py` (`GET ""` with `Depends(current_account)` and `get_session`, `response_model=AccountResponse`; a `None` account raises
  the same `HTTPException(401, headers={"WWW-Authenticate": "Bearer"})` as `current_account`, so the route has one 401; `current_account` is declared before the session so a bad token needs no database); `openapi.json` (generated, never by hand).
- layer: router + schemas; the route holds no query (rule of ADR-0011).
- test: `tests/e2e/test_http_account.py` (app built as in `test_http_require_roles.py`): AC1 to AC4 and AC8 (AC3 asserts the `WWW-Authenticate` header; AC4 also runs on `running_client(create_app(Settings()))` with no database; response keys exactly the contract; no
  `hash`, `salt`, `otp*`, `refreshToken` anywhere in the body); `tests/unit/test_openapi_stale.py` and `test_response_models.py` run as they are.
- executed how (evidence): scratchpad script with its own scratch database (`DATABASE_URL` exported explicitly), `alembic upgrade head`, seeds, one throwaway
  secret pair; create a password account and a phone-only account through the service, mint tokens, run `uv run poc-base-fast-api` (secrets and `DATABASE_URL` exported, never written to `.env`); `curl -i` with a valid token (both
  accounts), a deleted account's token, a garbage token and none; expect 200, 200 (`phoneNumber: null`), 401, 401, 401. Paste the responses.
- risk: whether `current_account` claim name is `account_id` (it is, per `require_roles`).

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker or `TEST_DATABASE_URL`),
`uv run python -m app.cli --export-openapi --check`. Anything not run goes under "Not verified".

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-5.3/spec.md (ACs checked off)
- [ ] docs/ARCHITECTURE.md: `services/account.py`, `schemas/account.py`, the first real route; the "one route exists" sentence; the data-truth paragraph (the service writes Account rows)
- [ ] docs/api/ENDPOINTS.md: the `account` row marked built; the Token checks bullet notes that this route rejects a missing or deleted account
- [ ] docs/DOMAIN_GLOSSARY.md: no new term
- [ ] docs/decisions/ADR-0022: P7's role layer is "any authenticated account" for self-scoped routes (Q1, decided by the human); the route has no `require_roles`
- [ ] stale promises corrected in this PR: `app/dependencies.py` docstring (5.3 "will" reject a deleted account), ENDPOINTS line 14 ("403 until 5.3"), `app/schemas/account_profile.py` docstring (response model now exists)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Q1: a role-less token reads its own account | accepted by the human (token only) | decided, ADR-0022 records it |
| A half-built account on a duplicate | an orphan row if the caller commits anyway | AC7 test: after the `IntegrityError`, roll back and count rows |
| Eager load of profile adds a query per call | none at this scale | `selectinload` keeps it at two statements |

## Estimate
R1 M, R2 M.

## Assumptions
Q1 decided by the human in session (token only, ADR-0022); Q2, Q3 of the spec. The caller owns the transaction. The caller passes a ready password hash and salt.

## Not covered
Hashing, sign-up/sign-in routes, 409 mapping, profile update, cache, rejecting deleted accounts in other guarded routes.
