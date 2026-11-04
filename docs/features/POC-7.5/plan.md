# POC-7.5 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     A deliberate exception is written the same way, with its reason:
     Approved-by: spike, no review — <TICKET> -->
Approved-by: Volodymyr · 2026-11-04 — A1 (write conditional on the checked hash), A2 (soft-deleted account → 401 INVALID_CREDENTIALS) and A6 (no throttle on guessing the current password, I.8) accepted as proposed; recorded by the agent on the user's chat approval "aproved". Container removal was not authorised: `poc-7-5-pg` stays running and is named in the PR.

Pattern followed: `app/services/password_auth.py` `find_credential` + `check` (7.3: read as plain values, route rolls back, one Argon2 check, dummy hash when nothing matches) for the check, and
`TokenService.rotate` in `app/services/tokens.py` (7.4: one UPDATE conditional on the value that was checked, no row means rejected, flush never commit, ADR-0021) for the write; the route follows
`sign_out` and `sign_in` in `app/routers/auth.py` (guard first, then session and service, route owns the commit; routes-convention 3 to 5). Behaviour from Node `changePassword` in
`jwt-auth-strategy.service.ts` and `change-password.e2e-spec.ts`, read. No new pattern, so no ADR; no new service, so no new provider.

## Contract changes
- boundary: new `POST /api/v1/auth/password/change` (204, Bearer, `ChangePasswordInput` already exists in `app/schemas/auth.py`); additive. `openapi.json` regenerated with `uv run python -m app.cli --export-openapi`.
- data: none, no migration. `hash` replaced, `salt` null, six columns nulled in the one UPDATE (`refreshToken`, `resetTokenHash`, `resetTokenExpiresAt`, `otpHash`, `otpSalt`, `otpExpiresAt`).
- internal API: `PasswordAuthService.find_credential_for_account(account_id) -> PasswordCredential` and `change(credential, current_password, new_password) -> None` (raises `InvalidCredentialsError`); 7.6 reuses the clearing set and adds its own write-time confirm.
- tests: `lock_waiters` and `wait_for_a_lock_waiter` move from `tests/e2e/test_db_token_service.py` to `tests/utils/locks.py` (new; `tests/utils/db.py` is synchronous fixtures only) so the second race test does not copy them (rule D1); behaviour unchanged.
- dependencies: none new.

## Requirements (ordered; branch `feat/POC-7.5-change-password`, one draft PR, one commit each)

### R1 — PasswordAuthService.change (M)
- files: `app/services/password_auth.py` (`find_credential_for_account`: same filters as `find_credential` (live account, live identity, non-null hash) but by account id;
  `change`: `await self.check(credential, current)` (so the service cannot change without checking), `hash_secret(new)` before any query, then
  `UPDATE "AccountIdentity" SET hash = :new, salt = NULL, refreshToken = NULL, resetTokenHash = NULL, resetTokenExpiresAt = NULL, otpHash = NULL, otpSalt = NULL, otpExpiresAt = NULL
  WHERE accountId = :id AND hash = :checked AND deleted = false AND EXISTS(live account) RETURNING id`; no row → `InvalidCredentialsError`; flush, never commit; docstring tasks 7.3, 7.5),
  `tests/utils/locks.py` (new: the two lock helpers moved), `tests/e2e/test_db_token_service.py` (imports them).
- layer: services. test: `tests/e2e/test_db_password_auth_service.py` (extend, `db_session`): AC1 (new hash verifies new and not old, `salt` null), AC3 (all six columns set beforehand, null after), AC4 (wrong current: nothing changed),
  AC5 (OTP-only, soft-deleted account, soft-deleted identity), and the race (AC6) on two sessions from `db_engine`: A calls `change` and holds its transaction, B calls `change` with the same stale credential and the right current password,
  blocks on its UPDATE; the test waits for a lock waiter (bounded), commits A, B raises `InvalidCredentialsError`, the stored hash verifies A's password only. Written first; must fail 3 of 3 without `AND hash = :checked`.
- executed how: R3.
- risk: moving the helpers touches a 7.4 test file; its tests must stay green.

### R2 — the route and the contract (M)
- files: `app/routers/auth.py` (`POST /password/change` 204: `claims = Depends(current_account)` listed first, body, `session`, `password_auth`; `credential = await find_credential_for_account(...)`, `await session.rollback()`
  (no pooled connection through Argon2, as `sign_in`), `await change(credential, body.current_password, body.new_password)`, `await session.commit()`), `openapi.json` (generated),
  `docs/api/ENDPOINTS.md` (`changePassword` row marked built; line 70 gets the write-time confirm and the 401 for a soft-deleted account; the 7.3 note on the sign-in window points here), `docs/RUNBOOK.md` (change password),
  `tests/utils/auth.py` docstring only if it lists routes.
- layer: routers. No logic beyond guard → read → rollback → service → commit.
- test: `tests/e2e/test_http_auth_change_password.py` (new; ports `change-password.e2e-spec.ts` (5 cases)): AC1 to AC5 over HTTP (old password 401, new 200, refresh token from before 401 `UNAUTHORIZED`, wrong current changes nothing, OTP-only account from OTP verify,
  soft-deleted account), AC7 (no, garbage, expired via `frozen_clock.shift`, refresh-as-Bearer; each also with an invalid body), AC8 parametrized 422 cases, AC9, AC10 (`JsonFormatter` pass; a pool test with `hash_secret` and `verify_secret` both watched,
  `pool.checkedout() == [0]` each; must fail without the route's `rollback()`), and a pending OTP code requested before the change no longer verifying. `test_response_models.py`, `test_openapi_stale.py` keep passing.
- executed how: R3.

### R3 — execute for real (S, no code)
- Throwaway PostGIS on port 5545 (no volume; the untracked `dump.rdb` stays), `APP_ENV=local`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5545/poc` and generated `JWT_*` secrets exported in every shell, `uv run alembic current` to confirm the target, `upgrade head`, `alembic check`, `uv run poc-base-fast-api`.
  `curl`: sign-up, sign-in (keep the refresh token), `POST /password/change` with a wrong current (401 `INVALID_CREDENTIALS`), with the right one (204, empty body), sign-in old (401), sign-in new (200), refresh with the pre-change token (401),
  `GET /account` with the pre-change access token (200), change with no header (401). `select` on the identity: `hash` prefix, `salt` null, the six columns null (set `resetTokenHash` and an OTP first by hand/`otp/request`). Grep server output for both passwords and every token: none. Paste request/response in the PR.
  Teardown: stop the server (`pkill`); the container `poc-7-5-pg` (my own, named, no volume) is removed with `docker rm -f poc-7-5-pg` only if the approval message says so (rule C4); otherwise it stays running and the PR body names it.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker), `uv run python -m app.cli --export-openapi --check`, `uv run alembic check` (against the R3 database), `uv build`.

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-7.5/spec.md (ACs ticked)
- [ ] docs/ARCHITECTURE.md: layout row (`PasswordAuthService.find_credential_for_account`, `change`), "Where data truth lives" (the change writes `hash` and clears six columns), "Nine routes exist" → ten, "Key flows"
- [ ] docs/DOMAIN_GLOSSARY.md: "Secret hash" row (passwords can now be replaced, the old one stops working); no new term
- [ ] docs/api/ENDPOINTS.md, docs/RUNBOOK.md (R2); ADR-0028 and ADR-0008 need no edit
- [ ] scope doc row 7.5 status: a human edits the Claude Docs doc (listed in the PR body)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Two changes (or a change and a reset) race between the check and the write | an old password's holder overwrites a newer one | conditional UPDATE on the checked hash; the lock-waiter race test of R1 is written first and must fail without it |
| Argon2 (verify and hash) runs with a pooled connection held | pool starvation by an authenticated caller | route `rollback()` before `change`; the watched-pool test in R2 must fail without it |
| A stolen access token guesses the current password, unthrottled | brute force through an authenticated route | out of scope (I.8, A6): state it in the PR, build no limiter |
| Moving the lock helpers breaks the 7.4 race test | lost coverage | run `tests/e2e/test_db_token_service.py` after R1; the mutation check of 7.4 still fails without the swap condition |
| The 422 body echoes a password | secret in a response and logs | the error handler already hides custom-validator input (4.2); AC8 asserts the body and a log pass checks it |

## Assumptions
- A1 to A6 of spec.md; A1 (conditional write), A2 (soft-deleted account gets 401) and A6 (no throttle on guessing the current password) are F2 decisions: the `Approved-by:` line names them, and they are repeated in the PR body. One PR for 7.5 only (rule A4); no change to CI files, `pyproject.toml`, `uv.lock` or migrations.
