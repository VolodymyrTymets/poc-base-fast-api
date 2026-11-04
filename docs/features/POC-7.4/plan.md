# POC-7.4 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     A deliberate exception is written the same way, with its reason:
     Approved-by: spike, no review — <TICKET> -->
Approved-by: Volodymyr · 2026-11-04 — A1 (soft-deleted account or identity → 401 on refresh) and A2 (sign-out with no identity row → 204, idempotent) accepted as proposed; recorded by the agent on the user's chat approval "approved"

Pattern followed: `app/services/tokens.py` `TokenService.issue` (7.2: upsert of the refresh hash, flush never commit, ADR-0021) and `OtpService.spend` (7.2: one conditional UPDATE with a row-count check
decides a race); `app/routers/auth.py` for the routes (routes-convention 3 to 5); `refresh_account` and `current_account` in `app/dependencies.py` (4.4) for the guards, listed before the session
(routes-convention 4). Behaviour from Node `jwt-auth-strategy.service.ts` (`validateRefreshToken`, `refreshToken`), `auth.service.ts` (`signOut`), `jwt-refresh.strategy.ts` and `refresh-token.e2e-spec.ts`, read.
No new pattern, so no ADR. No new service, so no new provider: both operations are the lifecycle of the refresh token, which `TokenService` already owns.

## Contract changes
- boundary: new `POST /api/v1/auth/refresh` (200 `TokenResponse`, security scheme `x-refresh-token`) and `POST /api/v1/auth/sign-out` (204, Bearer); additive. `openapi.json` regenerated with `uv run python -m app.cli --export-openapi`.
- data: none, no migration. `refreshToken`, `otpHash`, `otpSalt`, `otpExpiresAt` exist; sign-out nulls them, refresh replaces `refreshToken`.
- internal API: `TokenService.rotate(account_id, presented_token) -> TokenPair` (raises `UnauthorizedError`), `TokenService.revoke(account_id) -> None`; `refresh_credentials` dependency returning `RefreshCredentials(account_id, token)`
  (`token` `repr=False`); `refresh_account` is unchanged, so its 4.4 tests stand. 7.5 and 7.6 may reuse `revoke`'s clearing.
- dependencies: none new.

## Requirements (ordered; branch `feat/POC-7.4-refresh-sign-out`, one draft PR, one commit each)

### R1 — TokenService.rotate and revoke (M)
- files: `app/services/tokens.py` (`rotate`: one SELECT of the stored hash of a live identity of a live account, `token_matches(presented, stored)` else `UnauthorizedError`, then `issue_token` x2 and
  `UPDATE "AccountIdentity" SET refreshToken = :new WHERE accountId = :id AND refreshToken = :stored AND deleted = false RETURNING id`, no row → `UnauthorizedError`; flush, never commit.
  `revoke`: one UPDATE setting `refreshToken`, `otpHash`, `otpSalt`, `otpExpiresAt` to null where `accountId = :id`, no row-count check (A2). Module docstring: tasks 7.2, 7.4.)
- layer: services. test: `tests/e2e/test_db_token_service.py` (extend, `db_session`): rotate gives a pair whose stored hash is sha256 of the new refresh and differs from the old (AC1, AC2);
  no stored hash, wrong token, access token string, a token of another account → `UnauthorizedError` (AC4); soft-deleted account and identity (AC5); revoke nulls the four columns and leaves `hash` and `salt` (AC7);
  revoke with no identity row does nothing (AC8); the race (AC6) on two sessions from `db_engine`, each committing its own work and the setup committed first, with no seam in the service: session A calls `rotate` and holds its transaction open (it holds the row lock);
  session B, in a task, calls `rotate` with the same token, reads the old hash, matches, and blocks on its UPDATE; the test polls `pg_stat_activity` for a lock waiter (a condition with a bound, `asyncio.wait_for`, never a sleep), then commits A: B raises `UnauthorizedError`
  because its UPDATE re-checks `refreshToken` against the hash it read; the stored hash is A's. Written first and must fail without the `AND refreshToken = :stored` condition (B would win too). Ports `jwt-strategy` refresh cases.
- executed how: R4.
- risk: the lock-waiter poll is Postgres-specific (`pg_stat_activity.wait_event_type = 'Lock'`); the tests already require a real Postgres (P8).

### R2 — refresh_credentials dependency (S)
- files: `app/dependencies.py` (`RefreshCredentials` frozen dataclass; `refresh_credentials` depends on `refresh_account` first and on `_refresh_header`, returns the claims' account id with the raw token; docstring task list 7.4, and fix the `refresh_account` docstring that says 7.4 will compare).
- layer: dependencies. test: `tests/e2e/test_http_auth_dependencies.py` (extend; it already runs an app with `database_url=None`): a valid token reaches a stub route with the same token, a bad one is 401 `UNAUTHORIZED` before any database is needed.
- executed how: R4.

### R3 — the two routes and the contract (M)
- files: `app/routers/auth.py` (`POST /refresh` 200 `response_model=TokenResponse`: `credentials` listed before `session` and `tokens`, `pair = await tokens.rotate(...)`, `await session.commit()`;
  `POST /sign-out` 204 `response_class=Response`: `claims = Depends(current_account)` first, `await tokens.revoke(claims.account_id)`, `await session.commit()`; a failed rotate never commits),
  `openapi.json` (generated), `docs/api/ENDPOINTS.md` (`refreshToken` and `signOut` rows marked built; line 69 "task 7.4 decides the REST answer" becomes the answer: 204, idempotent (A2); line 13 "the match with the stored refresh hash by task 7.4" says it is built in 7.4; mapping decision 16 (line 122, "Proposed, still open for the refresh-token check") becomes "Decided in POC-7.4" with the approver's answer to A1), `docs/RUNBOOK.md` (refresh and sign-out), `tests/utils/auth.py` docstring (refresh route exists), `tests/e2e/test_http_auth_helper.py` (the `_refreshing` stub keeps its job only if no real route offers it: replace it by the real `POST /auth/refresh`, each changed assertion with `# WHY:` (B3), listed in the PR body).
- layer: routers. No logic beyond guard → service → commit (routes-convention 3 to 5).
- test: `tests/e2e/test_http_auth_refresh.py` (new; ports `refresh-token.e2e-spec.ts`: refresh, invalid, expired via `frozen_clock.shift(timedelta(days=8))`) AC1 to AC6 over HTTP incl. two parallel posts, the old token after a refresh, the access token as refresh token;
  `tests/e2e/test_http_auth_sign_out.py` (new) AC7 to AC9: sign-up, sign-out, old refresh 401, `GET /account` 200, OTP code requested then sign-out then verify 401, no-identity account, a soft-deleted account and a second sign-out 204 (A2); AC10 with a `JsonFormatter` pass in each file.
  `test_response_models.py` (204 is exempt already) and `test_openapi_stale.py` keep passing.
- executed how: R4.

### R4 — execute for real (S, no code)
- Throwaway PostGIS on port 5544 (no volume; the untracked `dump.rdb` stays), `APP_ENV=local`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5544/poc` and generated `JWT_*` secrets exported in every shell, `uv run alembic current` to confirm the target, `upgrade head`, `uv run poc-base-fast-api`.
  `curl`: sign-up, `POST /refresh` (200, new pair), the old refresh token again (401), the new one (200), `POST /sign-out` (204, empty body), the last refresh token (401), `GET /account` with the old access token (200), sign-out with no header (401).
  `select left("refreshToken",8), "otpHash" is null` on the identity before and after, and the sha256 of the returned refresh token computed outside the app equals the stored value. Grep server output for any token: none. Paste request/response in the PR.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker), `uv run python -m app.cli --export-openapi --check`, `uv run alembic check` (against the R4 database), `uv build`.

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-7.4/spec.md (ACs ticked)
- [ ] docs/ARCHITECTURE.md: layout row (`dependencies.py` `refresh_credentials`, `TokenService.rotate` and `revoke`), "Where data truth lives" (both write), "Seven routes exist" → nine, "Key flows" (refresh and sign-out)
- [ ] docs/DOMAIN_GLOSSARY.md: "Refresh token" row (single use: every refresh replaces it; sign-out clears it)
- [ ] docs/api/ENDPOINTS.md, docs/RUNBOOK.md (R3); ADR-0008 needs no edit (it already says sign-out clears the hash)
- [ ] scope doc row 7.4 status: a human edits the Claude Docs doc (listed in the PR body)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A replayed refresh token wins a race against its own rotation | one stolen token mints two live sessions | the conditional UPDATE on the hash just read; the barrier test of R1 is written first and must fail without it |
| A 401 body that differs between failures | lets a caller tell "signed out" from "never valid" | one `UnauthorizedError` for every path; AC3 to AC5 assert equal bodies |
| The race test passes for the wrong reason (B starts after A commits) | the CAS is untested | B must be seen waiting on the lock before A commits; mutation check: drop the `AND refreshToken = :stored` condition and the test must fail 3 of 3 runs |
| Rewriting the helper test weakens it (rule B3) | silent loss of coverage | keep every assertion, only the source of the 200/401 changes; `# WHY:` on each; list in the PR |
| `refresh_credentials` re-reads the header and drifts from `refresh_account` | a token accepted by one and not the other | it depends on `refresh_account`, never re-verifies |

## Assumptions
- A1 to A5 of spec.md; A1 and A2 are F2 decisions for the approver and are repeated in the PR body. One PR for 7.4 only (rule A4); no change to CI files, `pyproject.toml`, `uv.lock` or migrations.
