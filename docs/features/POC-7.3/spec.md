# POC-7.3 — Password sign-up and sign-in

## Problem
A client can sign in only by OTP (7.1, 7.2). The Node base also let a user register and sign in with an email and a password, and `web/`-style
clients and the test auth helper (`tests/utils/auth.py`) expect `POST /auth/sign-up` and `POST /auth/sign-in`. Today both paths answer 404 and the
helper is proven only against stub routes (issue I.10 note).

## Goal / business value
Goal 2 (Authentication: a working, understandable pipeline a new POC can rely on as-is) and goal 3 (the helper's first real run).

## Scope
- in: `POST /api/v1/auth/sign-up` (201) and `POST /api/v1/auth/sign-in` (200), both answering `{accessToken, refreshToken}` (`TokenResponse`);
  `PasswordAuthService` (`app/services/password_auth.py`); password stored as Argon2id (ADR-0028, supersedes the "bcrypt 10 rounds" of the scope row);
  the unique-index race on the email mapped to 409; replacing the sign-up and sign-in stubs of `tests/e2e/test_http_auth_helper.py` by the real routes.
- **out (explicit):** refresh and sign-out (7.4), change password (7.5), restore and reset (7.6), rate limiting and email verification (I.8, P3),
  any change to `TokenService` or the models (`AccountService` changes only by an optional `password_salt`, see plan), a migration, a new dependency, CI files.

## Acceptance criteria
- [x] AC1 Given a new email and a valid password, when `POST /auth/sign-up`, then 201 with both tokens, a `CUSTOMER` account with a profile (email lowercased), an identity whose `hash` is Argon2id and whose `salt` is null, and `refreshToken` = sha256 of the returned refresh token.
- [x] AC2 Given an email already on any profile (also a soft-deleted one, or in another case), when sign-up, then 409 `EMAIL_ALREADY_REGISTERED` and no new row.
- [x] AC3 Given two concurrent sign-ups for one email, then one gets 201 and the other 409 (the unique index decides), and no 500.
- [x] AC4 Given a valid email and the right password, when `POST /auth/sign-in`, then 200 with tokens; the refresh hash is replaced, so the previous refresh token stops matching; the access token opens `GET /api/v1/account`.
- [x] AC5 Given an unknown email, a wrong password, an OTP-only account (no hash), a soft-deleted account, profile or identity, when sign-in, then one 401 `INVALID_CREDENTIALS` body for all.
- [x] AC6 Sign-in with an email in other letter case succeeds (same normalisation as sign-up).
- [x] AC7 Validation (already in `SignUpInput`/`SignInInput`, 4.3) is reachable over HTTP: 422 `VALIDATION_FAILED` with field names for a bad email, a password under 8 or over 72 bytes (sign-up), over 72 bytes or empty (sign-in), a control character, an unknown key.
- [x] AC8 No password, hash, token or email in any log line of either route (rules D8, P4).
- [x] AC9 `tests/e2e/test_http_auth_helper.py` runs against the real routes with its failure-message assertion unchanged in strength; `openapi.json` is current.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Email of an OTP account that has none | sign-up creates a new account (the phone account stays separate) | Node behaviour |
| Unknown email on sign-in | one dummy Argon2 verify, so the time matches a wrong password | assumption A1 |
| Password of exactly 72 bytes / 73 bytes | accepted / 422 | 4.3 |
| Sign-up whose commit fails | nothing remains (route never commits before tokens are issued) | ADR-0021 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Spend a dummy Argon2 verify on an unknown email, no hash or a deleted identity (as 7.2 does for a phone)? | yes, reuse the 7.2 approach and a dummy hash of the same cost | **yes (F2, security)** |
| A2 | What does `AccountIdentity.salt` hold for a password? | null: the salt is inside the Argon2 string (ADR-0028 left this to 7.3 "unless it finds a reason"). This needs `create_password_account(..., password_salt: str \| None = None)`, the one change outside the new files: a `str` is required today, and a type-ignore or an empty string would break S3/D3. The alternative is a non-null placeholder. | **yes (F2, auth)** |
| A5 | Between the password check and the token issue the route holds no transaction, and `TokenService.issue` does not re-check the hash or `deleted` (unlike 7.2's conditional spend). Accept this window? | yes for 7.3: nothing writes those columns yet; 7.5 (change password) and 7.6 (reset) must add a write-time confirm when they land, and say so in their plans | **yes (F2, auth)** |
| A3 | Does sign-in update `Account.last_login_at`? | no: Node does not; unchanged behaviour | no |
| A4 | Sign-in's Argon2 check runs with no pooled connection held (read, rollback, verify), and sign-up hashes before touching the database | yes: both routes are unauthenticated and not rate limited (I.8), as in 7.2 | no |
