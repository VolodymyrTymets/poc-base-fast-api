# ADR-0008 — Refresh tokens stored as sha256, sent in a header

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.1
- **Supersedes:** none. It amends Node ADR-0004 (JWT access/refresh auth with OTP sign-in) and Node ADR-0011 (Email + password auth alongside OTP, with a log-only email worker), and closes the refresh-token item in Node ADR-0011's risk list. Decisions D5 and D6 of the scope doc; both confirmed by volodymyr on 2026-10-29.

## Context
The Node base stores the refresh token as a bcrypt hash of the whole JWT. bcrypt only reads the first 72 bytes, so everything after
them is ignored. In the Python `bcrypt` library, version 5.0.0 and later raise `ValueError` for input over 72 bytes, so that
design cannot be ported (source: pyca/bcrypt documentation, checked with Context7 on 2026-10-29). This is an authentication decision (rule F2).

## Decision
- Store `sha256(refreshToken)` in `AccountIdentity`, and compare with a constant-time function. A refresh token is a high-entropy random-looking value, so a fast hash is enough; bcrypt adds cost without adding safety here.
- Passwords stay bcrypt (10 rounds) with the 8 to 72 byte length check, because they are low-entropy and user-chosen.
- The refresh token travels in the `x-refresh-token` header on `POST /api/v1/auth/refresh`, as the Node base does. An httpOnly cookie remains a later option.
- Sign-out, password change and password reset clear the stored refresh hash.
- Access tokens are signed with the single `JWT_SECRET` (ADR-0010).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| bcrypt of base64(sha256(token)) (the library's own workaround) | works, but a slow hash buys nothing for a high-entropy token |
| Storing the raw refresh JWT | a database leak would hand out live sessions |
| httpOnly cookie now | changes the client contract and needs CSRF handling; out of scope |

## Consequences
- Positive: no truncation, no `ValueError`, cheap verification.
- Accepted cost: if the Python API is ever pointed at a database the Node API wrote, every existing session is logged out, because the stored values differ.
- Still open from Node ADR-0011 and out of scope here: no rate limiting, email change without re-authentication, repeated restore requests replacing the live token.
- Follow-ups: tasks 4.4, 7.2, 7.4.

## Revisit when
Refresh tokens move to opaque server-side sessions, or a cookie transport is adopted.
