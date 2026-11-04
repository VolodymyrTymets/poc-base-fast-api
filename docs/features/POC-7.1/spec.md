# POC-7.1 — POST /api/v1/auth/otp/request (and issue I.10)

## Problem
Nothing issues a sign-in code yet: the notifier (6.3) and the account service (5.3) exist, the `/auth` router is empty. A phone number must be able to ask for a
one-time code, which is stored only as a hash, valid 2 minutes, and delivered as an SMS job. Separately, two e2e tests fail on `main` (issue I.10, "do before package 7");
7.1 is the first route that relies on the auth test helper, so they are fixed here (decision of Volodymyr, 2026-11-04: one PR, against rule A4's one-requirement default).

## Goal / business value
Goal 2 (authentication): the first half of the OTP sign-in a new POC relies on. Goal 3: a green e2e baseline before package 7 builds on it.

## Scope
- in: `POST /api/v1/auth/otp/request` (`{phoneNumber}` → 200 `{success: true, code?: string}`); `OtpService` (`app/services/otp.py`) with code generation, hashing and
  verification helpers (7.2 reuses `verify_code`); `get_otp_service` provider; `OtpRequestResponse` in `schemas/auth.py`; the hashing seam `app/core/hashing.py`
  on `pwdlib[argon2]` (new runtime dependency, approved by Volodymyr, 2026-11-04) and an ADR recording it; I.10: find the cause of each failing test and fix the test or the code.
- behaviour (ENDPOINTS.md `signInOtp`): the phone is normalised by `PhoneNumber`; an unknown phone creates a customer account (`AccountService.create_customer`);
  a 6-digit code (`secrets.randbelow`, 100000–999999) is hashed and stored on `AccountIdentity` with `otpExpiresAt = now + 2 min` (identity row created when missing);
  a new request replaces the previous code; the account's live phone gets the `send_totp_code` job through `NotifierService` **after** the commit; `code` is in the body only for
  `APP_ENV` local, development or test.
- **out (explicit):** `POST /otp/verify` and token issuance (7.2), sign-up/sign-in and password hashing (7.3, which will reuse `app/core/hashing.py`), rate limiting and attempt limits (I.8, P3),
  a real SMS provider, de-duplicating concurrent first requests for one phone (no unique index on the phone, as in Node), cache (9.x), any other route.

## Acceptance criteria
- [ ] AC1 Unknown phone: 200 `{success: true, code}` (test env), one new `CUSTOMER` account with profile phone, role link and identity; a second request for the same phone adds no account.
- [ ] AC2 The stored `otpHash` is an Argon2 hash that `verify_code(code, hash)` accepts and never equals or contains the code; `otpExpiresAt` is exactly 2 minutes after the (frozen) clock; a later request replaces hash and expiry.
- [ ] AC3 An account that already has a password identity keeps its `hash` and `salt`; only the OTP columns change.
- [ ] AC4 Exactly one `send_totp_code(phone, code)` job is enqueued per request, only after the commit (a job never refers to a code the database lacks).
- [ ] AC5 `code` is absent from the body (key not present) when `APP_ENV=production`; present for local, development, test.
- [ ] AC6 A malformed or missing `phoneNumber`, or an extra key, is 422 `VALIDATION_FAILED` and creates nothing.
- [ ] AC7 Redis down: the call still answers 200 (logged by the notifier, 6.3); no log line holds the code or the phone (rules D8, P4).
- [ ] AC8 Ported from Node `otp-code-generator` spec: a 6-character digit string in [100000, 999999], varying across calls; hash differs per call for one code; wrong, empty and foreign-hash codes verify false.
- [ ] AC9 I.10: both tests pass with no `.env` in the working directory and under the developer's `.env`; no assertion weakened (rule B3).
- [ ] AC10 `openapi.json` regenerated; the stale test passes; the response model holds no ORM class.

## Edge cases
| Case | Expected | Decided by |
|------|----------|-----------|
| Identity row missing (customer made by 5.3 has none) | created in the same transaction | Node `upsert` |
| Two concurrent first requests for one phone | possibly two accounts; the oldest wins on lookup | existing comment in `AccountService.get_by_phone` |
| Identity soft-deleted | upsert leaves `deleted` alone; nothing sets it today | assumption A3 |
| Commit fails | nothing queued, error propagates as 500 | AC4 |
| `otpSalt` column | not written (Argon2 keeps its salt in the hash string); set to null on each request | assumption A2 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | bcrypt or pwdlib[argon2] | `pwdlib[argon2]`, one cost profile in `app/core/hashing.py` | answered: pwdlib[argon2] (Volodymyr, 2026-11-04). The scope doc says bcrypt: the ADR records the departure and 7.3 inherits it |
| Q2 | Argon2 cost | OWASP minimum profile (19 MiB, t=2, p=1) instead of the 64 MiB library default: `/otp/request` is unauthenticated and unlimited (I.8), so memory per request matters. Parameter names to be read from the installed source (rule D4) | yes (security, rule F2): write the answer here. Answer: accepted as proposed (Volodymyr, 2026-11-04, "approved" after the profile was named) |
| Q3 | I.10 in this PR | yes, as one commit before the feature work | answered (Volodymyr, 2026-11-04) |
| Q4 | Hashing runs off the event loop | `asyncio.to_thread`; the hash is CPU and memory heavy | no |
