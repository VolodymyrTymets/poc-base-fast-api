# POC-5.3 — AccountService and GET /api/v1/account

## Problem
No code reads or creates an `Account`. Task 4.4 authenticates a token but never checks the account exists; the sign-in tasks (7.1, 7.3) need
`AccountService` to find or create accounts; and `GET /api/v1/account` (Node `account` query) is not built. Rows 4 and 5.3 of the scope doc.

## Goal / business value
Goal 2 (authentication pipeline): the account layer every sign-in flow stands on, and the first real guarded route a fork can copy.

## Scope
- in: `AccountService` in `app/services/account.py` (`get_by_id`, `get_by_phone`, `create_customer`, `create_password_account`); the response
  models in `app/schemas/account.py` (+ `AccountProfileResponse` in `app/schemas/account_profile.py`, reused by 5.4); `GET /api/v1/account` in
  `app/routers/account.py`; the regenerated `openapi.json`.
- **out (explicit):** password hashing (bcrypt arrives with 7.3; the service takes a ready `hash` and `salt`), OTP, token issue, sign-up/sign-in routes (7.x),
  profile update (5.4), mapping a duplicate email to 409 (7.3 owns the sign-up flow; here the unique index raises `IntegrityError`), read cache (9.2),
  deleted-account rejection in `current_account`/`require_roles` (this route only).

## Acceptance criteria
- [ ] AC1 Given a valid access token of an existing account, when `GET /api/v1/account`, then 200 `{id, createdAt, updatedAt, profile}` with `profile.email` of that account.
- [ ] AC2 Given a password account with no phone, then `profile.phoneNumber` is `null` (issue I.3).
- [ ] AC3 Given a valid token whose account does not exist or is soft-deleted, then 401 `UNAUTHORIZED` with the same `WWW-Authenticate: Bearer` challenge as `current_account` (ENDPOINTS decisions 2 and 16; decision 16 is still marked "proposed", this approval confirms it).
- [ ] AC4 Given no or a bad token, then 401 `UNAUTHORIZED` with `WWW-Authenticate: Bearer`; no database is needed to answer it (tested with an app that has no `DATABASE_URL`).
- [ ] AC5 `get_by_id` / `get_by_phone` return the account with its live profile loaded; a soft-deleted account is not returned; a soft-deleted profile is `None`.
- [ ] AC6 `create_customer(phone)` creates account, profile (phone) and the `CUSTOMER` role link in one flush; `create_password_account(email, hash, salt)` creates account, profile (email), identity and the `CUSTOMER` role link in one transaction; neither commits (ADR-0021).
- [ ] AC7 A second password account with the same email raises `IntegrityError`; after the caller rolls back, no account, profile, identity or role link of the failed call remains. (`phoneNumber` has no unique index in `0001_init`; a unique phone would be a separate decision with a new revision and ADR, not part of this ticket.)
- [ ] AC8 The response model holds no ORM class and carries no identity data (hash, salt, otp, tokens); `openapi.json` is regenerated and the stale test passes.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Account without a profile | `profile: null` | ENDPOINTS row `account` |
| Profile soft-deleted | `profile: null` | rule P6 |
| Role missing (unseeded DB) | `RoleNotFoundError`, a 500, not swallowed | 5.2 |
| `lastLoginAt` for a new account | set to now (UTC, naive) by the service; the column has no default | models |
| Caller has an account but no role | still 200: the route needs authentication only | ENDPOINTS decision 15 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Role layer on `GET /account`? | **Decided by the human: token only**, "any authenticated account" (ENDPOINTS decision 15); ownership is by construction. ADR-0022 records it | resolved |
| Q2 | Does `create_*` take the hash from the caller? | Yes; no new runtime dependency (rule C2) | no |
| Q3 | The 9 Node `account.service.spec.ts` cases | The Node repo is not in this workspace; the cases are re-derived from the service's behaviour (AC5 to AC7) and listed in the PR | no |
