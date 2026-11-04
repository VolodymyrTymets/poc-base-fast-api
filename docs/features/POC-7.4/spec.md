# POC-7.4 — Refresh token and sign-out

## Problem
A client that signed in (OTP 7.2, password 7.3) holds a 15 minute access token and a 7 day refresh token, but nothing accepts the refresh token and
nothing ends a session: `x-refresh-token` is verified by `refresh_account` (4.4) and never compared with the stored hash, and the stored hash can only be
replaced by a new sign-in.

## Goal / business value
Goal 2 (authentication a new POC can rely on as-is): the access/refresh pipeline of ADR-0008 is complete, and "an old refresh token is rejected after sign-out" holds.

## Scope
- in: `POST /api/v1/auth/refresh` (200, header `x-refresh-token`, no body, answers `TokenResponse`) and `POST /api/v1/auth/sign-out` (204, Bearer, no body);
  `TokenService.rotate` and `TokenService.revoke`; a `refresh_credentials` dependency that hands the route the raw header token next to its claims.
- **out (explicit):** an access-token denylist (a signed-out access token works until it expires, as in Node), refresh-token reuse detection or session families,
  device or multiple sessions, rate limiting (I.8), password change and reset (7.5, 7.6), any migration, new dependency or CI change.

## Acceptance criteria
- [x] AC1 Given a valid refresh token that matches the stored hash, when `POST /auth/refresh`, then 200 with a new pair, and the stored hash is the sha256 of the new refresh token.
- [x] AC2 Given that refresh succeeded, when the old refresh token is sent again, then 401 `UNAUTHORIZED`.
- [x] AC3 A missing, empty, malformed, tampered or expired refresh token, and an access token in `x-refresh-token`, give 401 `UNAUTHORIZED` over the real route.
- [x] AC4 A validly signed refresh token that no longer matches the stored hash (after sign-out, after a newer sign-in, or with no identity row) gives 401 `UNAUTHORIZED`.
- [x] AC5 A soft-deleted account or identity gives 401 `UNAUTHORIZED` on refresh.
- [x] AC6 Given two concurrent refreshes with the same token, then exactly one gets 200 and the other 401, and the stored hash belongs to the winner.
- [x] AC7 Given a valid Bearer token, when `POST /auth/sign-out`, then 204 with no body; `refreshToken`, `otpHash`, `otpSalt` and `otpExpiresAt` are null, the password `hash` is untouched, the previous refresh token is then 401, and the access token still opens `GET /account`.
- [x] AC8 Sign-out with a missing or bad Bearer token is 401 `UNAUTHORIZED`; sign-out for an account with no identity row, and a second sign-out, are 204.
- [x] AC9 A sign-in code requested before sign-out no longer verifies after it (401 `INVALID_CREDENTIALS`).
- [x] AC10 No token, hash or phone number in any log line of either route (rules D8, P4).
- [x] AC11 `openapi.json` is current and the response-model test passes (204 has no body).

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Refresh token of an account that never stored one (OTP-less, signed out) | 401 `UNAUTHORIZED`, same body as every other refresh failure | ADR-0008 |
| Refresh twice in parallel | one winner; the compare-and-swap on the stored hash decides | assumption A3 |
| Refresh failure body | `UNAUTHORIZED` (ENDPOINTS.md), never `INVALID_CREDENTIALS`: a client then signs in again | ENDPOINTS.md |
| Sign-out of a soft-deleted account | 204, nothing matters to clear | assumption A2 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Refresh for a soft-deleted account or identity (Node does not check)? | 401 `UNAUTHORIZED`, as `GET /account` does (ADR-0022) | **yes (F2, auth)** |
| A2 | Sign-out when the account has no identity row (Node's update throws)? | 204, idempotent: there is nothing to clear and a 401 would tell nothing the caller can act on | **yes (F2, auth)** |
| A3 | How is the stored hash checked? | `token_matches` (constant time, ADR-0008) on a read, then an UPDATE conditional on the hash just read, so a replayed token loses the race | no (ADR-0008) |
| A4 | Does refresh touch `last_login_at` or the OTP columns? | no, as Node | no |
| A5 | Does sign-out revoke the access token? | no, it stays valid until it expires (ENDPOINTS.md `signOut`); no denylist | no |
