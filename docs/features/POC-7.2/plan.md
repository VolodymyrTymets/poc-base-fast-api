# POC-7.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: spike, no review — <TICKET> -->
Approved-by: Volodymyr · 2026-11-04 — A1 (dummy Argon2 verify) and A2 (soft-deleted = not found) accepted as proposed; recorded by the agent on the user's chat approval Volodymyr - 2026-11-04

Pattern followed: `app/services/otp.py` + `app/routers/auth.py` (7.1: service over a session, flush never commit (ADR-0021), provider in `app/dependencies.py` (ADR-0025), route owns the commit,
routes-convention.md); `app/core/security.py` for the JWT codec (`issue_token`, built in 4.4); tests follow `tests/e2e/test_db_otp_service.py` and `tests/e2e/test_http_auth_otp_request.py`.
Behaviour from Node `otp-auth-strategy.service.ts` (`verifyOtp`) and `jwt-strategy.service.ts` (`refreshTokens`), read. No new pattern, so no ADR.

## Contract changes
- boundary: new `POST /api/v1/auth/otp/verify` and `TokenResponse` (additive); `openapi.json` regenerated with `uv run python -m app.cli --export-openapi`.
- data: none, no migration (`refreshToken`, `otpHash`, `otpSalt`, `otpExpiresAt`, `isPhoneVerified` exist). `refreshToken` now holds a sha256 hex (rule P5).
- internal API 7.3, 7.4, 7.5, 7.6 call: `TokenService.issue(account_id) -> TokenPair`, `hash_token`, `token_matches`, `get_token_service`.
- dependencies: none new (hashlib, hmac from the standard library).

## Requirements (ordered; branch `feat/POC-7.2-otp-verify`, one draft PR, one commit each)

### R1 — sha256 token hash helper (S)
- files: `app/core/hashing.py` (`hash_token(token) -> str` hex sha256 of UTF-8; `token_matches(token, stored) -> bool` via `hmac.compare_digest`, `False` for `None`), module docstring line.
- layer: core. test: `tests/unit/test_hashing.py` (extend): known vector, hex length 64, match/mismatch/None, not Argon2-prefixed.
- executed how: `uv run pytest tests/unit/test_hashing.py` plus a one-line `uv run python -c` printing `hash_token("x")`.

### R2 — TokenService and provider (M)
- files: `app/services/tokens.py` (`TokenPair(access_token, refresh_token)` dataclass with `repr=False` fields; `TokenService(session, settings)`; `issue(account_id)`: `issue_token` x2, upsert
  `AccountIdentity.refreshToken = hash_token(refresh)` with `INSERT … ON CONFLICT (accountId) DO UPDATE` setting only that column, flush, never commit), `app/dependencies.py` (`get_token_service(session, settings)`, docstring task list).
- layer: services, dependencies. `tests/unit/test_routers_use_service_providers.py` keeps passing.
- test: `tests/e2e/test_db_token_service.py` on `db_session` with the real database: pair verifies via `verify_token`; stored value equals `sha256(refresh)`; two issues differ and the second hash replaces the first; no identity row → created; password `hash`/`salt` untouched; `isPhoneVerified` stays false (ports the 6 `jwt-strategy` cases).
- executed how: R4.

### R3 — OtpService.verify (M)
- files: `app/services/otp.py`: `verify(phone_number, code) -> str` (account id). Order: `get_by_phone`; identity select (`deleted = false`); if no account/identity/hash/expiry or `expires_at <= utc_now()` → dummy `verify_secret` (A1) then `InvalidCredentialsError`;
  `verify_secret(code, hash)` false → `InvalidCredentialsError`; then one `UPDATE "AccountIdentity" SET otpHash=NULL, otpSalt=NULL, otpExpiresAt=NULL WHERE accountId=:id AND otpHash=:hash AND deleted = false` (row count must be 1, else `InvalidCredentialsError`: the code was already spent),
  then `UPDATE "AccountProfile" SET isPhoneVerified=true`; flush, never commit. Replace `verify_code`'s "7.2 checks the expiry" note.
- layer: services. test: `tests/e2e/test_db_otp_service.py` (extend; `frozen_clock`): every AC3 case incl. expiry at 2:00 and 2:01, AC2 clearing, AC4 double use and a concurrent pair on two sessions (`asyncio.gather`, one wins), AC6, soft-deleted account and soft-deleted identity (A2); a `JsonFormatter` pass over records for code/phone (AC8). Ports the 10 `verifyOtp` cases of `otp-auth-strategy.service.spec.ts`.
- concurrent test: `verify` never commits, so each coroutine given to `asyncio.gather` opens its own session from `db_engine`, calls `verify`, then commits (rolls back on `InvalidCredentialsError`); the second UPDATE waits for the first commit, then matches 0 rows: exactly one wins. Phones unique to the test (commits persist for the module). A test named for the boundary: at exactly 2:00 the code is expired (`<=`).
- executed how: R4.

### R4 — the route and the response model (M)
- files: `app/schemas/auth.py` (`TokenResponse`: `access_token`, `refresh_token`, camelCase aliases, like `OtpRequestResponse`), `app/routers/auth.py` (`POST /otp/verify`, 200, `response_model=TokenResponse`: `account_id = await otp.verify(...)` → `tokens.issue(account_id)` → `await session.commit()` → return;
  the 401 rolls back by never committing), `openapi.json` (generated), `docs/api/ENDPOINTS.md` (`verifyOtp` row marked built; documents 401 body), `docs/RUNBOOK.md` (sign-in step).
- layer: routers, schemas. No logic beyond the verify → issue → commit order (routes-convention 3, 5).
- test: `tests/e2e/test_http_auth_otp_verify.py`: request a code over HTTP, verify it (AC1, AC2 via `db_engine`), AC3 cases over HTTP, AC4 reuse, AC7 422 cases and the token opening `GET /api/v1/account`; ports `sign-in-otp.e2e-spec.ts` (5 cases: sign in, bad code, bad token on a guarded route, bad phone, expired access token via `frozen_clock`).
  `tests/unit/test_response_models.py` and `test_openapi_stale.py` keep passing.
- executed how: R5.

### R5 — execute for real (S, no code)
- Throwaway PostGIS + `redis:7-alpine`, no volume (the untracked `dump.rdb` stays); export `DATABASE_URL`, `REDIS_*`, `APP_ENV=local` in every shell, confirm with `uv run alembic current`, `alembic upgrade head`, `uv run poc-base-fast-api` and the worker.
  `curl` `/otp/request` for `+12125550142`, then `/otp/verify` with the returned code: paste request/response; `select "isPhoneVerified"` and `"refreshToken"` (64 hex chars, equals `sha256` of the returned refresh token computed outside the app); `curl GET /account` with the access token (200); repeat verify with the same code (401) and with a wrong code (401). Grep server and worker output for the code, the tokens and the full phone: none.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker), `uv run python -m app.cli --export-openapi --check`, `uv run alembic check`, `uv build`.

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-7.2/spec.md (ACs ticked)
- [ ] docs/ARCHITECTURE.md: layout row (`services/tokens.py`, `get_token_service`, `hash_token`), "Where data truth lives" (`TokenService.issue`, `OtpService.verify` write), "Four routes exist" → five, "Key flows: None implemented" (OTP sign-in now works)
- [ ] docs/DOMAIN_GLOSSARY.md: "Refresh token" row (stored as sha256, replaced on every issue); an "Access/refresh token pair" term only if the glossary lacks one
- [ ] docs/api/ENDPOINTS.md, docs/RUNBOOK.md (R4)
- [ ] scope doc row 7.2 status: a human edits the Claude Docs doc (listed in the PR body)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Two concurrent verifies both pass the Argon2 check, both spend the code | one code mints two sessions | conditional UPDATE with row-count check; the `asyncio.gather` test in R3 is written first and must fail without the guard |
| Unauthenticated 6-digit guess surface (10^6 values, no attempt limit) | brute force inside the 2 minute window | out of scope (I.8, ADR-0028 accepts it); state it in the PR, do not build a limiter |
| Argon2 verify while a transaction is open holds a pooled connection (7.1 noted this) | pool starvation under a flood | read identity, verify outside any write, then the short UPDATEs; measure with the R5 run |
| `isPhoneVerified` lives on `AccountProfile` and the profile may be soft-deleted | verified flag not set, silent | update by `accountId` and check the row count in R3's test |

## Assumptions
- A1 to A4 of spec.md; A1 and A2 are F2 decisions for the approver and are repeated in the PR body. One PR for 7.2 only (rule A4); no change to CI files, `pyproject.toml` or `uv.lock`.
