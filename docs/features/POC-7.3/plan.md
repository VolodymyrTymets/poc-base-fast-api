# POC-7.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     A deliberate exception is written the same way, with its reason:
     Approved-by: spike, no review — <TICKET> -->
Approved-by: Volodymyr · 2026-11-04 — A1 (dummy Argon2 verify), A2 (salt null, `password_salt: str | None = None`) and A5 (accepted window, 7.5/7.6 add a write-time confirm) accepted as proposed; recorded by the agent on the user's chat approval "approved"

Pattern followed: `app/services/otp.py` + `app/routers/auth.py` `verify_otp` (7.2: service over a session, flush never commit (ADR-0021), provider in `app/dependencies.py` (ADR-0025),
route owns the commit, find → rollback → Argon2 → write so no connection is held while hashing, dummy hash for the no-match path); `app/services/account.py` `create_password_account` and
`app/services/tokens.py` `TokenService.issue` are reused; the unique-email mapping follows `app/services/account_profile.py` (`EMAIL_UNIQUE_INDEX`, `_violated_index`, savepoint with `begin_nested`). Tests follow `tests/e2e/test_db_otp_service.py` and `tests/e2e/test_http_auth_otp_verify.py`.
Behaviour from Node `jwt-auth-strategy.service.ts` (`signUp`, `signIn`) and the `sign-up` / `sign-in` e2e specs in `../poc-base/api/test/auth/`, read. No new pattern, so no ADR.
Scope-row difference: the row says bcrypt 10 rounds; ADR-0028 (Argon2id through `hash_secret`) wins (CLAUDE.md P2).

## Contract changes
- boundary: new `POST /api/v1/auth/sign-up` (201) and `POST /api/v1/auth/sign-in` (200), both `TokenResponse`; additive. `openapi.json` regenerated with `uv run python -m app.cli --export-openapi`.
- data: none, no migration. `AccountIdentity.hash` holds an Argon2id string, `salt` stays null (A2 of spec.md).
- internal API changed: `AccountService.create_password_account(email, password_hash, password_salt: str | None = None)` (was a required `str`; the column is already nullable, existing callers pass a string and are unchanged); `_violated_index` moves to `app/core/db.py` as public `violated_index` and `account_profile.py` imports it; `_DUMMY_HASH` moves from `otp.py` to `app/core/hashing.py` as public `DUMMY_HASH` (one import line in `otp.py`). Behaviour-preserving moves, covered by the existing tests.
- internal API 7.5 and 7.6 call: `PasswordAuthService`, `get_password_auth_service`.
- dependencies: none new.

## Requirements (ordered; branch `feat/POC-7.3-password-auth`, one draft PR, one commit each)

### R1 — PasswordAuthService.sign_up and provider (M)
- files: `app/services/password_auth.py` (new): `PasswordAuthService(session, accounts: AccountService)`; `sign_up(email, password) -> str` (hash first with `hash_secret`, then pre-check any `AccountProfile.email == email` including
  deleted, then `create_password_account(email, hash)` inside `begin_nested()` like `AccountProfileService.update`; on `IntegrityError` whose `violated_index` is `EMAIL_UNIQUE_INDEX` raise `EmailAlreadyRegisteredError`, re-raise any other);
  `app/services/account.py` (signature, salt default `None`), `app/core/db.py` (public `violated_index`), `app/services/account_profile.py` (import it);
  `app/dependencies.py` (`get_password_auth_service`, docstring task list); `app/services/auth.py` stays untouched (its docstring already names `password_auth.py`).
- layer: services, dependencies. `tests/unit/test_routers_use_service_providers.py` keeps passing.
- test: `tests/e2e/test_db_account_service.py` (extend: a password account created with no salt has `salt` null); `tests/e2e/test_db_password_auth_service.py` (new, `db_session`): AC1 rows (profile email lowercased, role `CUSTOMER`, `hash` starts `$argon2id$`, `salt` null), AC2 (live, soft-deleted, other-case email), AC3 on two sessions from `db_engine` with `asyncio.gather`: each coroutine runs `sign_up` then `commit` (`rollback` on `EmailAlreadyRegisteredError`), inside `asyncio.wait_for` so a lock wait fails the test instead of hanging
  (emails unique to the test; written first and must fail without the constraint mapping). Ports the sign-up slice of `jwt-auth-strategy.service.spec.ts`.
- executed how: R4.
- risk: the two moves touch `account_profile.py` and `otp.py`; `uv run pytest tests/e2e/test_db_account_profile_service.py tests/e2e/test_db_otp_service.py` stays green.

### R2 — PasswordAuthService.find_credential and check (M)
- files: `app/services/password_auth.py`: `find_credential(email) -> PasswordCredential(account_id | None, hash | None)` (frozen dataclass, `hash` `repr=False`; live profile, live account, live identity, non-null hash, else both `None`);
  `check(credential, password) -> str` runs one `verify_secret` against `credential.hash or DUMMY_HASH` (the shared `DUMMY_HASH` of `app/core/hashing.py`, same cost as `hash_secret`) and raises `InvalidCredentialsError`, else returns the account id.
- layer: services. test: `tests/e2e/test_db_password_auth_service.py` (extend): AC5 every case (unknown, wrong, OTP-only identity without hash, soft-deleted account, profile and identity), AC6, and a spy asserting `verify_secret` runs once on the no-match path (A1). Ports the sign-in slice of the spec.
- executed how: R4.

### R3 — the two routes, helper test on real routes, contract (M)
- files: `app/routers/auth.py` (`POST /sign-up` 201 → `account_id = await service.sign_up(...)`, `tokens.issue`, `await session.commit()`; `POST /sign-in` 200 → `find_credential`, `await session.rollback()`, `check`, `tokens.issue`, commit; both `response_model=TokenResponse`),
  `openapi.json` (generated), `docs/api/ENDPOINTS.md` (`signUp` and `signIn` rows marked built; line 66 "task 7.3 decides what `salt` holds" becomes "`salt` stays null; the salt is in the Argon2 string"), `docs/RUNBOOK.md` (password sign-in), `tests/e2e/test_http_auth_helper.py`, rewritten test by test (each is a B3 item listed in the PR body, no assertion removed): the sign-up and sign-in stubs go and the helper hits the real routes; the access-header test calls the real `GET /api/v1/account`;
  the refresh-header test uses a stub `_refreshing` that checks the header with `verify_token` and the refresh secret (`POST /auth/refresh` is 7.4); the exact `AuthTokens(STUB_ACCESS, STUB_REFRESH)` equality becomes both tokens present and each accepted by its own check;
  the missing-token case (`MALFORMED_EMAIL`) keeps its stub on a separate bare `FastAPI()` through `client_for`, so the real router cannot shadow it; the failure-message case gets its 401 from the real sign-in; module docstring updated; each changed assertion carries `# WHY: real routes issue non-deterministic JWTs (POC-7.3)` (rule B3), `tests/utils/auth.py` docstring.
- layer: routers, schemas (no new model: `SignUpInput`, `SignInInput`, `TokenResponse` exist). No logic beyond the order above (routes-convention 3, 5).
- test: `tests/e2e/test_http_auth_sign_up.py` and `tests/e2e/test_http_auth_sign_in.py` (new): AC1 to AC7 over HTTP, AC4 token opens `GET /account` and the old refresh hash is replaced (via `db_engine`), AC8 with a `JsonFormatter` pass over captured records;
  ports `sign-up.e2e-spec.ts` and `sign-in.e2e-spec.ts`. plus, once in each file, a copy of `test_no_pooled_connection_is_held_while_the_code_is_hashed` (fails without the sign-in rollback / the hash-first order). `test_response_models.py`, `test_openapi_stale.py` keep passing.
- executed how: R4.

### R4 — execute for real (S, no code)
- Throwaway PostGIS on port 5543 (no volume; the untracked `dump.rdb` stays), `APP_ENV=local` and `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5543/poc` exported in every shell (a bare `.env` may point at the developer's own database), `uv run alembic current` to confirm the target, then `upgrade head`, `uv run poc-base-fast-api`. `curl` sign-up (201), the same email in other case (409), sign-in right/wrong/unknown (200/401/401),
  `GET /account` with the access token (200); `select email, left(hash,10), salt, left("refreshToken",8)` on the identity; sha256 of the returned refresh token computed outside the app equals the stored value; grep server output for the password, the hash and the email: none. Paste request/response in the PR.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker), `uv run python -m app.cli --export-openapi --check`, `uv run alembic check`, `uv build`.

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-7.3/spec.md (ACs ticked)
- [ ] docs/ARCHITECTURE.md: layout row (`services/password_auth.py`, `get_password_auth_service`), "Where data truth lives" (`PasswordAuthService.sign_up` writes; `create_password_account` now has a caller), "Five routes exist" → seven, "Key flows"
- [ ] docs/DOMAIN_GLOSSARY.md: "Secret hash" row (passwords now used, `salt` stays null); no new term otherwise
- [ ] docs/api/ENDPOINTS.md, docs/RUNBOOK.md (R3); `docs/decisions/ADR-0028` gets no edit (it already defers the salt to 7.3: record the answer in ARCHITECTURE.md)
- [ ] scope doc row 7.3 status: a human edits the Claude Docs doc (listed in the PR body)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Two concurrent sign-ups pass the pre-check | 500 or two accounts for one email | the unique index plus the constraint-name mapping; the `asyncio.gather` test of R1 is written first and must fail without it |
| Email enumeration through sign-in timing or body | registered emails revealed | one body for every failure and a dummy Argon2 verify (A1); R2 spy test; sign-up's 409 reveals existence by contract (ENDPOINTS.md) |
| Argon2 with a pooled connection held on unauthenticated routes | pool starvation under a flood | hash before the first query in sign-up, rollback before `check` in sign-in; copy 7.2's `test_no_pooled_connection_is_held_while_the_code_is_hashed` for both routes |
| Replacing the helper stubs weakens `test_http_auth_helper.py` (rule B3) | silent loss of coverage | keep every assertion; only the source of the 401/201 changes; say so in the PR |
| Failed flush in sign-up poisons the session | later statements fail | savepoint (`begin_nested`) as in `AccountProfileService.update`; AC3 test |

## Assumptions
- A1 to A4 of spec.md; A1 and A2 are F2 decisions for the approver and are repeated in the PR body. One PR for 7.3 only (rule A4); no change to CI files, `pyproject.toml`, `uv.lock` or migrations.
