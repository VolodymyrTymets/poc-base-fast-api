# POC-7.6 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     A deliberate exception is written the same way, with its reason:
     Approved-by: spike, no review — <TICKET> -->
Approved-by: Volodymyr · 2026-11-04 — A1 (restore timing can tell known from unknown emails, accepted), A2 (the token is never in a response), A3 (an OTP-only account sets its first password through restore and reset) and A6 (anyone who knows an email can replace its pending token, I.8) accepted as proposed; recorded by the agent on the user's chat approval "approved". Container removal was not authorised: `poc-7-5-pg` and the R4 containers stay running and are named in the PR.

Pattern followed: `OtpService.issue` + `deliver` and `POST /otp/request` in `app/services/otp.py` and `app/routers/auth.py` (7.1: issue, route commits, then deliver after the commit; unauthenticated; the notifier hides a down queue, ADR-0027);
`PasswordAuthService.find_credential_for_account` + `change` (7.5: read as plain values, route `rollback()`, Argon2, one conditional UPDATE, no row means rejected, flush never commit, ADR-0021) for `reset`;
`TokenService.rotate` (7.4) for the conditional write and its lock-waiter race test (`tests/utils/locks.py`, 7.5). Behaviour from Node `restorePassword`/`resetPassword` in `jwt-auth-strategy.service.ts` and `restore-password.e2e-spec.ts`, read.
No new pattern, so no ADR. The service is built from another service (the notifier): ADR-0027.

## Contract changes
- boundary: new `POST /api/v1/auth/password/restore` (200 `RestorePasswordResponse {success}`) and `POST /api/v1/auth/password/reset` (204); both unauthenticated; additive. `openapi.json` regenerated with `uv run python -m app.cli --export-openapi`.
- data: none, no migration (`resetTokenHash`, `resetTokenExpiresAt` and a unique index on the hash exist). Restore may create an `AccountIdentity` row for an OTP-only account.
- internal API: `PasswordAuthService(session, accounts, notifier)` (constructor gains the notifier; `get_password_auth_service` depends on `get_notifier_service`), `issue_reset_token(email) -> IssuedReset | None`, `deliver_reset_token(issued | None)`,
  `find_reset_challenge(token) -> ResetChallenge`, `reset(challenge, new_password)`; the six-column clearing set of `change` becomes a private helper both use.
- tests: the `service()` helper of `tests/e2e/test_db_password_auth_service.py` builds the notifier with a `FakeQueue` (as `test_db_otp_service.py` does).
- dependencies: none new (`secrets`, `hashlib`).

## Requirements (ordered; branch `feat/POC-7.6-restore-reset-password`, one draft PR, one commit each)

### R1 — restore: issue_reset_token, deliver_reset_token, notifier wiring (M)
- files: `app/services/password_auth.py` (`IssuedReset(account_id, token)` with `token` `repr=False`; `RESET_TOKEN_TTL = timedelta(minutes=30)`; `issue_reset_token`: live profile by email, live account, identity not soft-deleted or absent, else `None`;
  `secrets.token_hex(32)`, `hash_token`, one `INSERT ... ON CONFLICT (accountId) DO UPDATE SET resetTokenHash, resetTokenExpiresAt WHERE deleted = false RETURNING id` (a missing identity row is created; the table has no `updatedAt`; no row, an identity soft-deleted in between, returns `None`), flush; `deliver_reset_token`: `None` is a no-op, else `notifier.notify_about_password_reset(account_id, token, [NotifierType.EMAIL])`; the shared clearing helper),
  `app/dependencies.py` (provider takes the notifier), `tests/e2e/test_db_password_auth_service.py` (helper builds the notifier).
- layer: services, dependencies. `tests/unit/test_routers_use_service_providers.py` keeps passing.
- test: `tests/e2e/test_db_password_auth_service.py` (extend, `db_session`, `frozen_clock` after the database fixtures): AC1 (stored value is sha256 of a 64 hex token and not the token; expiry is `FROZEN_NOW` + 30 min), AC2 (unknown; soft-deleted profile, account, identity: `None`, nothing written),
  AC3 (second issue replaces the first), AC4 (OTP-only: no identity row, and identity with no hash), delivery (one `send_password_reset` job with the token, none for `None`, a down queue not raised), and no token in `JsonFormatter` output.
- executed how: R4.

### R2 — reset: find_reset_challenge and reset (M)
- files: `app/services/password_auth.py` (`ResetChallenge(identity_id | None, token_hash)` plain values, `token_hash` `repr=False`; `find_reset_challenge(token)`: select by `hash_token(token)`, identity and account live, `resetTokenExpiresAt > utc_now()`, else an empty challenge;
  `reset(challenge, new_password)`: empty challenge raises `InvalidResetTokenError` before any hashing, else `hash_secret(new)` then `UPDATE ... SET hash, salt NULL + the clearing set WHERE id = :id AND resetTokenHash = :hash AND resetTokenExpiresAt > :now AND deleted = false AND EXISTS(live account) RETURNING id`; no row raises `InvalidResetTokenError`; flush, never commit).
- layer: services. test: `tests/e2e/test_db_password_auth_service.py` (extend): AC5 (new password checks out through `find_credential` + `check`, six columns and `salt` null), AC7 (unknown, used twice, expired by `frozen_clock.shift(31 min)`, expired between read and write, soft-deleted account and identity; password unchanged),
  AC4 (an OTP-only account's first password), AC11 (an empty challenge never calls `hash_secret`, a spy), and the race (AC8) on two sessions from `db_engine`: A resets and holds its transaction, B resets with the same stale challenge and blocks, `wait_for_a_lock_waiter`, A commits, B raises `InvalidResetTokenError`,
  the stored hash verifies A's password only. Written first; must fail 3 of 3 without the token conditions of the UPDATE. Both `resetTokenHash` and `resetTokenExpiresAt` go null when a token is consumed, so either condition alone already rejects the loser: the mutation removes both (checked), a second test (expiry between read and write) pins the expiry one, and a third (a second restore between read and write) pins the hash one: each fails 3 of 3 without its condition.
- executed how: R4.

### R3 — the two routes and the contract (M)
- files: `app/schemas/auth.py` (`RestorePasswordResponse {success}`, camelCase config like `OtpRequestResponse`), `app/routers/auth.py` (`POST /password/restore`: `issued = await issue_reset_token(body.email)`, `await session.commit()`, `await deliver_reset_token(issued)`, `return {success: True}`;
  `POST /password/reset` 204: `challenge = await find_reset_challenge(body.token)`, `await session.rollback()`, `await reset(challenge, body.new_password)`, `await session.commit()`), `openapi.json` (generated),
  `docs/api/ENDPOINTS.md` (`restorePassword` and `resetPassword` rows built; the timing note A1; "decided in POC-7.6": a token is never in a body; the "Logging (rule P4)" bullet at line 35 gets the ADR-0026 exception: the reset job logs the recipient and token in `local`, `development` and `test`), `docs/RUNBOOK.md` ("Forgot password": restore, read the token from the worker log, reset).
- layer: routers, schemas. No logic beyond order (routes-convention 3 to 5).
- test: `tests/e2e/test_http_auth_restore_password.py` (new; ports `restore-password.e2e-spec.ts`): the flow with the token read from the `FakeQueue` job (old password 401, new 200), AC1 body exactly `{"success": true}`, AC2 same body and no job, AC3, AC4, AC5/AC6 (refresh before the reset is 401), AC7 over HTTP (reused, expired by `frozen_clock`, garbage; one body), AC9 parametrized 422, AC10 (`JsonFormatter` pass over API logs),
  AC11 (watched pool: `hash_secret` sees `checkedout() == 0`; must fail without the route's `rollback()`). `test_response_models.py`, `test_openapi_stale.py` keep passing.
- executed how: R4.

### R4 — execute for real, worker included (S, no code)
- Throwaway PostGIS (`poc-7-6-pg`, port 5546) and `redis:7-alpine` (`poc-7-6-redis`, port 6390), no volumes (the untracked `dump.rdb` stays); `APP_ENV=local`, `DATABASE_URL`, `REDIS_HOST=localhost`, `REDIS_PORT=6390` and generated `JWT_*` exported in every shell, `uv run alembic current`, `upgrade head`, `alembic check`.
  Start `uv run poc-base-fast-api` and `uv run arq app.worker.WorkerSettings`. `curl`: sign-up, restore (200, `{"success":true}`), restore for an unknown email (same body), read the token from the worker log, reset with a wrong token (400 `INVALID_RESET_TOKEN`), reset (204), sign-in old (401) and new (200),
  refresh with the pre-reset token (401), the token again (400). `select` the identity: the six columns and `salt` null, hash prefix; before restore `resetTokenHash` null and after it 64 hex equal to sha256 of the logged token computed outside the app. Grep the API log for the token and both passwords: none.
  Teardown: stop the API and the worker; the containers `poc-7-6-pg` and `poc-7-6-redis` (mine, named, no volume) and the leftover `poc-7-5-pg` are removed only if the approval message says so (rule C4); otherwise they stay and the PR names them.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker), `uv run python -m app.cli --export-openapi --check`, `uv run alembic check` (against the R4 database), `uv build`.

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-7.6/spec.md (ACs ticked)
- [ ] docs/ARCHITECTURE.md: layout row (`PasswordAuthService` methods and the notifier), "Where data truth lives" (restore writes the reset columns, reset replaces `hash`), "Ten routes exist" → twelve, "Key flows" (forgot password)
- [ ] docs/DOMAIN_GLOSSARY.md: "Password reset token" row (restore, reset, 30 minutes, single use, never in a response)
- [ ] docs/api/ENDPOINTS.md, docs/RUNBOOK.md (R3); ADR-0026 and ADR-0027 need no edit
- [ ] scope doc row 7.6 status: a human edits the Claude Docs doc (listed in the PR body)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Two resets with one token both apply | one token sets two passwords | conditional UPDATE on the token hash; the lock-waiter race test of R2 is written first and must fail without it |
| Restore tells known from unknown emails (body, queue, timing) | email enumeration | one body and no token in it (AC1, AC2); timing accepted as A1 and stated in the PR |
| The token leaks through a response, a log or a repr | account takeover | `repr=False`, notifier logs ids only, AC10 log pass, R4 grep |
| Argon2 on an unauthenticated route | CPU and pool abuse | an empty challenge never hashes (AC11 spy); the route `rollback()` before hashing, a watched-pool test that must fail without it |
| A sign-in that read the old credentials finishes after a reset and stores a refresh hash | a session outlives the reset | the gap of POC-7.5 review; not fixed here, awaiting the owner; repeated in the PR |
| Adding the notifier to `PasswordAuthService` breaks existing callers | red tests in 7.3 to 7.5 | the only constructors are the provider and one test helper; run those test files after R1 |

## Assumptions
- A1 to A7 of spec.md; A1, A2, A3 and A6 are F2 decisions: the `Approved-by:` line names them, and they are repeated in the PR body. One PR for 7.6 only (rule A4); no change to CI files, `pyproject.toml`, `uv.lock` or migrations.
