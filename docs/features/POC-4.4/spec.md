# POC-4.4 — JWT and auth dependencies

## Problem
No code can issue or check a token yet. Tasks 5.2 (roles), 7.x (auth routes) and 8.x (files) all need a token codec and the two
FastAPI dependencies that turn a header into an authenticated caller.

## Goal / business value
Goal 2 (authentication): one understandable, tested token layer that the later routes reuse as-is. ADR-0008 (refresh token, header
transport), ADR-0010 (one secret per token type, 15m default) and ENDPOINTS.md decision 14 (`typ` claim) are already settled.

## Scope
- in: PyJWT HS256 codec in `app/core/security.py` (issue and verify access and refresh tokens, payload `{sub, jti, typ}`, `exp`, `iat`);
  duration parser (`15m`, `55min`, `7d`, `30s`, `2h`); four settings (`JWT_SECRET`, `JWT_REFRESH_TOKEN_SECRET`,
  `JWT_ACCESS_TOKEN_EXPIRES_IN`, `JWT_REFRESH_TOKEN_EXPIRES_IN`); dependencies `current_account` (Bearer) and `refresh_account`
  (`x-refresh-token`) in `app/dependencies.py`; both return a small typed `TokenClaims` (account id, jti).
- **out (explicit):** loading the account from the database, soft-delete check, "account no longer exists" (task 5.3 / decision 16);
  comparing the refresh token with the stored sha256 hash (7.4); sha256 helper and the stored-hash write (7.2); `require_roles` (5.2);
  any route; a new error code (`UnauthorizedError` exists).

## Acceptance criteria
- [ ] AC1 Given no `Authorization` header, a non-Bearer scheme, an empty token, an expired token or a tampered token, when a route uses `current_account`, then 401 `UNAUTHORIZED` in the contract body.
- [ ] AC2 Given a valid access token, when the route runs, then the handler receives `TokenClaims` with the token's `sub` and `jti`.
- [ ] AC3 Same three cases for `refresh_account` with `x-refresh-token`.
- [ ] AC4 An access token is rejected by `refresh_account` and a refresh token by `current_account` (secret differs and `typ` differs; test both separately).
- [ ] AC5 A token signed with `alg=none` or HS384, or missing `sub`, `jti`, `typ` or `exp`, is rejected.
- [ ] AC6 `parse_duration` accepts `s`, `m`, `min`, `h`, `d` and raises on anything else (`15`, `1w`, `-5m`, `0m`, empty).
- [ ] AC7 No token or secret is logged or put in an error body or `details` (rules D8, P4); a secret never appears in `repr(Settings)`.
- [ ] AC8 A missing secret fails loudly (see Q1), never signs with an empty or default key.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| `Authorization: bearer x` (lowercase scheme) | accepted, scheme is case-insensitive (RFC 7235) | assumption |
| `sub` not a UUID string | 401 | assumption |
| clock skew | no leeway; `exp` is checked exactly (tests use `frozen_clock`) | assumption |
| 401 response | carries `WWW-Authenticate: Bearer` for `current_account`; the `refresh_account` 401 has none | assumption |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Secrets unset: boot or fail? | `jwt_secret` and `jwt_refresh_token_secret` are `SecretStr \| None`; the app boots without them (tests, health), a token operation raises a configuration error (500). `development` and `production` fail at boot unless both are set, at least 32 chars and different. | yes, security (F2) |
| Q2 | New runtime dependency `pyjwt` (C2) | approved by the task text naming PyJWT; `uv add pyjwt` | confirm with Approved-by |
| Q3 | Does `current_account` hit the database? | No. 4.4 depends on D5 and D9 only; the DB lookup arrives with 5.3 and wraps this dependency. | no |
