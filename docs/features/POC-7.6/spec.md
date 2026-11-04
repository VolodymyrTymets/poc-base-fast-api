# POC-7.6 — Restore and reset password

## Problem
A user who forgot a password has no way back in: `restore` (ask for a reset token by email) and `reset` (set a new password with it) do not exist. An account created by OTP, which has no password, has no way to get its first one either.

## Goal / business value
Goal 2 (authentication a new POC can rely on as-is): the forgotten-password flow works end to end, finishing from the worker log while no email provider is wired (ADR-0026), and is safe to expose unauthenticated.

## Scope
- in: `POST /api/v1/auth/password/restore` (200 `{success: true}`, body `{email}`) and `POST /api/v1/auth/password/reset` (204, body `{token, newPassword}`);
  `PasswordAuthService` gains `issue_reset_token`, `deliver_reset_token`, `find_reset_challenge` and `reset`, and the notifier; the clearing set shared with `change` (7.5);
  a random 32-byte token stored as sha256 with a 30 minute expiry; the email job queued after the commit.
- **out (explicit):** a real email provider (log-only, P3), rate limiting and the "repeated restore replaces the live token" risk (I.8), email verification, the sign-in side of the race found in POC-7.5 review (`TokenService.issue` is unconditional; awaiting the owner's decision),
  a reset link or URL (the token is the only artefact), tokens in any response body, any migration, new dependency or CI change.

## Acceptance criteria
- [x] AC1 Given a registered email, when `POST /auth/password/restore`, then 200 `{"success": true}` with no token in the body, `resetTokenHash` holds the sha256 of a 64 hex character token (never the token), `resetTokenExpiresAt` is 30 minutes ahead, and one `send_password_reset` job carries the token after the commit.
- [x] AC2 An unknown email, and an email on a soft-deleted profile, account or identity, answer the same 200 body and enqueue nothing.
- [x] AC3 A second restore replaces the first token: the first no longer resets, the second does.
- [x] AC4 An OTP-only account that has an email (no identity row yet, or an identity with no hash) gets a token; after a reset it signs in with its first password.
- [x] AC5 Given a valid token and a valid new password, when `POST /auth/password/reset`, then 204 with no body; the new password signs in, the old one is 401 `INVALID_CREDENTIALS`, and `refreshToken`, `resetTokenHash`, `resetTokenExpiresAt`, `otpHash`, `otpSalt`, `otpExpiresAt` are null, `salt` null.
- [x] AC6 The refresh token issued before the reset is rejected by `POST /auth/refresh`; an access token already issued works until it expires.
- [x] AC7 An unknown, already used, expired (30 minutes) or soft-deleted-account token is one 400 `INVALID_RESET_TOKEN`, and changes nothing; expiry is also checked at write time.
- [x] AC8 Given two resets racing with the same token, then exactly one is applied; the other is 400 `INVALID_RESET_TOKEN` and its password is not stored.
- [x] AC9 A malformed email, a token empty or over 200 characters, a new password under 8 or over 72 bytes or with a control character, and an unknown key are 422 `VALIDATION_FAILED` naming the field.
- [x] AC10 The token appears in no response body and in no log line of the API (it appears in the worker log only in `local`, `development` and `test`, ADR-0026); no password or hash in any log.
- [x] AC11 A reset with a garbage token runs no Argon2 work, and the Argon2 hash of a valid reset holds no pooled DB connection.
- [x] AC12 The RUNBOOK "forgot password" flow works from the worker log against a running API and worker; `openapi.json` is current.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Restore for a known email vs an unknown one, measured by response time | known does a write and a queue call, unknown a read only; accepted, not equalised | assumption A1 |
| Queue (Redis) down on restore | 200, the notifier logs `could not queue send_password_reset`, no email is sent | ADR-0027 |
| A change-password lands after restore | `change` clears the pending token, so the later reset is 400 | 7.5 |
| New password equals the old one | accepted | as 7.5 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | `restore` answers the same body for known and unknown emails, but a known one costs a DB write and a queue call, so response time can tell them apart. Accept (no rate limiting, I.8)? | yes, documented; not equalised | **yes (F2, security)** |
| A2 | The token is never in a response, in any environment (a developer finishes the flow from the worker log, ADR-0026)? | yes | **yes (F2, security)** |
| A3 | An OTP-only account may set its first password through restore and reset, as Node? | yes | **yes (F2, auth)** |
| A4 | The reset write is one UPDATE conditional on the token hash, the expiry and a live identity and account; no row is `INVALID_RESET_TOKEN`? | yes (the ticket's "row count checked") | no |
| A5 | An email on a soft-deleted profile, account or identity is treated as unknown (no token, no email)? | yes, as Node | no |
| A6 | A restore replaces a live token, so anyone who knows an email can invalidate its pending reset (I.8). Accept for the POC? | yes, carried over, stated in the PR | **yes (F2, security)** |
| A7 | Argon2 for the new password runs only after the token was found valid and the read transaction ended? | yes, so a garbage token costs no Argon2 | no |
