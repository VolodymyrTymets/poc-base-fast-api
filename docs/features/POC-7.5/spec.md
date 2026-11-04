# POC-7.5 — Change password

## Problem
A signed-in user with a password cannot change it. A stolen password stays valid, and nothing ends the sessions that were opened with it.

## Goal / business value
Goal 2 (authentication a new POC can rely on as-is): password accounts can rotate their credential, and the old password and every refresh token issued before stop working.

## Scope
- in: `POST /api/v1/auth/password/change` (204, Bearer, body `{currentPassword, newPassword}`); `PasswordAuthService.change` and `find_credential_for_account`;
  one UPDATE that stores the new Argon2id hash and clears the refresh hash, the reset token (hash and expiry) and the OTP (hash, salt, expiry); the write-time confirm that 7.3's assumption A5 deferred to this task.
- **out (explicit):** a first password for an OTP-only account (that is `restore`/`reset`, 7.6), tokens in the answer (the account signs in again), revoking the access token in use, rate limiting (I.8),
  re-authentication on email change (I.8), password history or "new differs from current" rules, any migration, new dependency or CI change.

## Acceptance criteria
- [x] AC1 Given a valid Bearer token and the right current password, when `POST /auth/password/change`, then 204 with no body, and `hash` is a new Argon2id string that verifies the new password and not the old one; `salt` is null.
- [x] AC2 Afterwards sign-in with the old password is 401 `INVALID_CREDENTIALS` and with the new password is 200.
- [x] AC3 The refresh token issued before the change is rejected by `POST /auth/refresh` (401 `UNAUTHORIZED`); `refreshToken`, `resetTokenHash`, `resetTokenExpiresAt`, `otpHash`, `otpSalt` and `otpExpiresAt` are null.
- [x] AC4 A wrong current password is 401 `INVALID_CREDENTIALS` and changes nothing (the old password still signs in, the refresh token still works).
- [x] AC5 An OTP-only account (no hash), a soft-deleted account and a soft-deleted identity are the same 401 `INVALID_CREDENTIALS`.
- [x] AC6 Given two changes racing from the same stored hash, then exactly one is applied; the other is 401 `INVALID_CREDENTIALS` and its new password is not stored.
- [x] AC7 A missing, malformed or expired Bearer token, and a refresh token as Bearer, are 401 `UNAUTHORIZED`, also when the body is invalid (the guard comes first).
- [x] AC8 A new password under 8 or over 72 bytes, with a control character, an empty current password, and an unknown key are 422 `VALIDATION_FAILED` naming the field.
- [x] AC9 The access token used for the call still opens `GET /account` until it expires.
- [x] AC10 No password, hash or token in any log line (rules D8, P4); neither Argon2 step holds a pooled DB connection.
- [x] AC11 `openapi.json` is current; the 204 route passes the response-model test.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| New password equals the current one | accepted, new hash, sessions still revoked | assumption A5 |
| Pending OTP code requested before the change | no longer verifies | Node behaviour, AC3 |
| Pending password-reset token | cleared; 7.6's reset then answers `INVALID_RESET_TOKEN` | Node behaviour, AC3 |
| Wrong current password, repeated | 401 each time; not rate limited | I.8, out of scope |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Between the current-password check and the write the route holds no transaction (7.3 A5). Make the write conditional on the hash that was checked? | yes: `UPDATE ... WHERE hash = :checked`; no row → 401 `INVALID_CREDENTIALS`. It also closes 7.3's A5 for this route | **yes (F2, auth)** |
| A2 | A valid Bearer token of a soft-deleted account (Node checks only the identity)? | 401 `INVALID_CREDENTIALS`, as sign-in does | **yes (F2, auth)** |
| A3 | OTP-only account (no hash) calls change? | 401 `INVALID_CREDENTIALS` as in Node; it sets a first password through 7.6 | no |
| A4 | Does the answer carry new tokens? | no, 204; the account signs in again (ENDPOINTS.md) | no |
| A5 | May the new password equal the current one? | yes, as Node | no |
| A6 | A stolen access token can guess the current password through this route, unthrottled (I.8). Accept for the POC? | yes, carried over and out of scope; stated in the PR | **yes (F2, security)** |
