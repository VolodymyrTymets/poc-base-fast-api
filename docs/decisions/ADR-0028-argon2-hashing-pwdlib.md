# ADR-0028 — Sign-in codes and passwords are hashed with Argon2id through pwdlib

- **Date:** 2026-11-04
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-7.1
- **Supersedes:** the password bullet of ADR-0008 ("Passwords stay bcrypt (10 rounds) with the 8 to 72 byte length check") and the scope doc's "bcrypt" for the sign-in code (task 7.1) and for passwords (task 7.3). ADR-0008's other bullets stand, above all the sha256 refresh token.

## Context
Task 7.1 stores the sign-in code (OTP) as a hash, and task 7.3 will store passwords. The scope doc and ADR-0008 say bcrypt, which is not a dependency of this repo. Adding a
dependency needs approval (rule C2), and this is an authentication decision (rule F2). Volodymyr chose `pwdlib[argon2]` over `bcrypt` on 2026-11-04.

## Decision
- One seam, `app/core/hashing.py`: `hash_secret` and `verify_secret`, Argon2id through `pwdlib` 0.3.1 (`pwdlib[argon2]`, which brings `argon2-cffi`). Both run in a worker thread.
- Cost: OWASP's minimum Argon2id profile, 19 MiB of memory, 2 iterations, 1 lane (`m=19456,t=2,p=1`), not the library default of 64 MiB. `POST /auth/otp/request` is unauthenticated and not
  rate limited (issue I.8, out of scope), so memory per request is the amplification a flood gets. The profile was accepted by volodymyr on 2026-11-04.
- The salt and the parameters are inside the hash string. `AccountIdentity.otpSalt` and `salt` are not written by the sign-in code path; the columns stay for schema parity (ADR-0015,
  ADR-0019). Task 7.3 decides what it writes to `salt` for passwords (a null, as the OTP path does, unless it finds a reason).
- A string that is not a readable Argon2 hash verifies `False` and is logged without its value. Any other error propagates.
- The 8 to 72 byte password check (`app/core/validation.py`) is unchanged by this ADR: Argon2 has no 72-byte limit, but changing the contract of the request models is not part of task 7.1.
  Task 7.3 may relax the upper bound only through its own decision.
- Refresh tokens and reset tokens stay sha256 (ADR-0008).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `bcrypt` (the scope doc) | an older algorithm, a 72-byte input limit, and a second dependency for 7.3 would have followed anyway; the choice was made for Argon2 |
| `hashlib.scrypt` from the standard library | no new dependency, but no upgrade path for parameters and a hand-written encoding of salt and cost |
| HMAC-SHA256 with a server secret | fast, so a leaked 6-digit code hash is brute-forced offline in moments; needs a new secret setting |
| The library default (64 MiB) | the unauthenticated endpoint would cost 64 MiB per request in flight |

## Consequences
- Positive: one modern algorithm for codes and passwords; parameters can change later, because `verify_and_update` on `PasswordHash` re-hashes an outdated value.
- Accepted cost: a hash made by the Node base (bcrypt) is not readable here, so sign-in with a password from a Node database fails; a Node database is not a target of this base (ADR-0008, ADR-0019).
- Accepted cost: a 6-digit code has only 10^6 values, so no hash makes an offline attack impossible; the 2-minute expiry and a future attempt limit (I.8) are the real protection.
- Accepted cost: the profile costs about 19 MiB per concurrent hash; a flood is bounded only by the process's own concurrency until rate limiting exists.
- Follow-ups: 7.1, 7.2 (verify), 7.3 (passwords); `docs/api/ENDPOINTS.md` wording follows.

## Revisit when
Rate limiting lands (the cost may rise), or a Node database must be served (add the bcrypt extra and a second hasher).
