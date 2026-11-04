# POC-7.2 — token issuance and POST /api/v1/auth/otp/verify

## Problem
A phone number can get a sign-in code (7.1) but cannot exchange it for a session: nothing issues the access/refresh pair, nothing stores the refresh hash, and nothing
checks a code. Tasks 7.3 (sign-up/sign-in) and 7.4 (refresh) need the same token issuance, so it is built once, here.

## Goal / business value
Goal 2 (authentication): completes the OTP sign-in a new POC relies on, and settles the refresh-token storage (rule P5, ADR-0008) that 7.3 to 7.6 reuse.

## Scope
- in: `POST /api/v1/auth/otp/verify` (`{phoneNumber, code}` → 200 `{accessToken, refreshToken}`); `TokenService` (`app/services/tokens.py`): issue the pair for an account and store
  `sha256(refreshToken)` in `AccountIdentity.refreshToken` (identity row created when missing), replacing the previous hash; `OtpService.verify` (unknown account, no identity, no code,
  expired or wrong code → `InvalidCredentialsError`; success consumes the code and sets `AccountProfile.isPhoneVerified`); `get_token_service` provider; `TokenResponse` in `schemas/auth.py`;
  a sha256 helper with constant-time compare in `app/core/hashing.py` (7.4 uses the compare).
- behaviour (ENDPOINTS.md `verifyOtp`, mapping decisions 4, 13, 14): all failures are 401 `INVALID_CREDENTIALS` (never `UNAUTHORIZED`, which triggers a client refresh); expiry is checked
  against `utc_now()`; the code is single-use even under two concurrent verifies (one conditional UPDATE, row count checked, as 7.6 does for reset tokens); a new pair replaces
  the stored hash, so the previous refresh token is dead.
- **out (explicit):** `POST /auth/refresh` and the stored-hash comparison (7.4), sign-out (7.4), sign-up/sign-in (7.3), attempt limits and rate limiting (I.8, P3), a soft-deleted
  account policy beyond "a deleted account is not found" (7.4 decides the refresh check), `openapi` consumers (no `web/`).

## Acceptance criteria
- [x] AC1 Valid code for a known phone: 200 `{accessToken, refreshToken}`; the access token verifies with `JWT_SECRET` and `typ=access`, the refresh token with `JWT_REFRESH_TOKEN_SECRET` and `typ=refresh`, both `sub` = the account id.
- [x] AC2 After success `otpHash`, `otpSalt`, `otpExpiresAt` are null, `AccountProfile.isPhoneVerified` is true, and `AccountIdentity.refreshToken` is `sha256(refreshToken)` in hex (never the token, never bcrypt/Argon2).
- [x] AC3 Unknown phone, account without identity, null `otpHash`, expired code (clock shifted past 2 minutes) and wrong code are each 401 `INVALID_CREDENTIALS` with one message; a failed call changes nothing (`isPhoneVerified` stays false, the code survives).
- [x] AC4 The same code used twice: the second call is 401. Two concurrent verifies of one code: exactly one 200.
- [x] AC5 Two verifies in a row give different refresh tokens, and the stored hash is the second one's (ported `jwt-strategy` cases). Issuing tokens through `TokenService` alone does not set `isPhoneVerified`.
- [x] AC6 A password identity on the same account keeps its `hash` and `salt` through verify (only OTP columns and `refreshToken` change).
- [x] AC7 Malformed phone, `code` over 6 characters or missing, or an extra key: 422 `VALIDATION_FAILED`. An access token from the response opens `GET /api/v1/account` (the end-to-end proof).
- [x] AC8 No log line from the call holds a code, token or phone (rules D8, P4); `openapi.json` regenerated and the stale check passes.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Soft-deleted account or identity | treated as not found: 401 `INVALID_CREDENTIALS` | assumption A2 |
| `code` is 6 digits but has leading/trailing spaces | wrong code, 401 (no trimming; the model only caps length) | ENDPOINTS.md |
| Expired and wrong code | the same 401 body | mapping decision 4 |
| Unknown phone timing | a dummy Argon2 verify keeps the time close to the known-phone path | assumption A1 |
| Redis down | not involved (verify enqueues nothing) | — |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Spend a dummy Argon2 verify on an unknown phone/no code, so 401 timing does not reveal registered numbers? | yes, one module-level dummy hash | **yes (F2, security)** |
| A2 | A soft-deleted account/identity on verify? | not found, 401; the identity read and the spend UPDATE filter `deleted = false` | **yes (F2, auth)** |
| A3 | Refresh `jti`: keep uuid4 hex from 4.4 (Node used 4 random bytes)? | keep, already built | no |
| A4 | Where does sha256 live? | `app/core/hashing.py` (`hash_token`, `token_matches`), next to the Argon2 seam, no new ADR (ADR-0008 already decides it) | no |
