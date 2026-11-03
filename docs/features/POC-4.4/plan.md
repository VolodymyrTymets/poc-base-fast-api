# POC-4.4 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-11-03 · Q1 as stated · pyjwt runtime dep (approved in chat; line recorded by the agent on their instruction)

Pattern followed: `app/core/errors.py` (one `core/` module per concern, no layer imports, `ClassVar`-typed, no `Any`) for `security.py`;
`app/core/db.py` `get_session` (reads `request.app.state`) for the dependencies; tests follow `tests/unit/test_errors.py` and
`tests/e2e/test_http_errors.py` (test-local routes on `create_app(Settings())` through `running_client`, no database). No precedent for
a token codec, but it stays inside ADR-0008 and ADR-0010, so no ADR. Layers: `core` (codec), `dependencies` (may use `core` and `config`).

## Contract changes
- boundary: none yet, no route uses the dependencies; `openapi.json` should not change (stale test confirms).
- config: four new settings, names fixed by ADR-0010; `.env.example` already lists them (header comment updated to say task 4.4 reads them).
- dependencies: `uv add pyjwt` (runtime). `uv.lock` through uv only (T3); `pyproject.toml` is ask-first.
- data: none.

## Requirements (ordered; branch `feat/POC-4.4-jwt-auth-dependencies`, one draft PR, one commit each)

### R1 — PyJWT, duration parser and settings (S)
- files: `pyproject.toml`, `uv.lock` (via `uv add pyjwt`); `app/config.py` (change: four fields; `SecretStr | None` secrets; `parse_duration` lives here; the two durations are validated at boot and stored as `timedelta`; the non-local rule of Q1); `.env.example` (comment: task 4.4 reads these); `.env.development.example` (comment: `development` rejects the placeholders, set real secrets of 32+ characters).
- layer: config (imports no `core`; `core/security.py` reads `Settings`, per ADR-0011).
- test: `tests/unit/test_config.py` — duration table (AC6: `15m`, `55min`, `7d`, `30s`, `2h` ok; `15`, `1w`, `-5m`, `0m`, empty fail), defaults (15m, 7d), bad duration stops the boot naming the field, secrets absent from `repr`, `development`/`production` without secrets, with short secrets or with equal secrets fail, `local`/`test` boot without.
- executed how: `uv run python -c` building `Settings()` with and without the env vars, and with `APP_ENV=development` plus the `.env.development.example` placeholders (expected boot error); paste output.
- risk: confirmed by grep: `tests/unit/test_sentry.py`, `tests/unit/test_openapi_export.py` and `tests/e2e/test_http_errors.py` build `Settings(app_env="production")` with no secrets. Q1's boot rule breaks them; each gets two placeholder secrets (a small, stated edit in this PR), or the human picks the lighter Q1 option (fail only when a token is issued or checked).

### R2 — Codec in `app/core/security.py` (M)
- files: `app/core/security.py` (new): `TokenType` (StrEnum), `TokenClaims` (frozen dataclass: `account_id`, `jti`), `issue_token(settings, account_id, type)`, `verify_token(settings, token, type)`. Verify: `algorithms=["HS256"]` pinned, `options={"require": ["exp","iat","sub","jti","typ"]}`, `typ` equality check, `sub` must be a UUID; every `jwt.PyJWTError` and bad claim becomes `UnauthorizedError` with a fixed message (no token text); missing secret raises `AuthConfigurationError(RuntimeError)`, not an `AppError` (no new error code): it reaches the existing 500 handler, its message names the setting, never a value. PyJWT API checked with Context7 before use (rule D4).
- layer: core.
- test: `tests/unit/test_security.py` — round-trip; expired via `frozen_clock.shift`; tampered signature; `alg=none`; HS384; each missing claim; wrong `typ` with the right secret; wrong secret; message and `details` contain no token fragment (AC5, AC7).
- executed how: `uv run python -c` issuing a token and verifying a good and a tampered one.
- risk: PyJWT 2.10+ rejects a non-string `sub`; we always issue a string. `time-machine` and PyJWT's `datetime.now`: confirmed by the expiry test.

### R3 — Dependencies and HTTP proof (M)
- files: `app/dependencies.py` (change: `current_account` using `HTTPBearer(auto_error=False)`, `refresh_account` using `APIKeyHeader(name="x-refresh-token", auto_error=False)`; `auto_error=False` so the contract body, not FastAPI's, is returned; `current_account` turns the codec's `UnauthorizedError` into `HTTPException(401, headers={"WWW-Authenticate": "Bearer"})`, which the existing handler maps to `UNAUTHORIZED` and keeps the header of, so `errors.py` stays untouched); `app/main.py` (change: `app.state.settings = settings`, one line).
- layer: dependencies, main.
- test: `tests/e2e/test_http_auth_dependencies.py` — test-local routes on `create_app(Settings(jwt_secret=..., ...))`: AC1 cases, AC2, AC3, AC4, 401 body shape and `WWW-Authenticate` on the Bearer one; no token in `caplog`.
- executed how (evidence): scratchpad script serving those routes with `uvicorn`, then `curl -i` with no header, a tampered token, an expired token and a valid token; paste responses.
- risk: `HTTPBearer` in the OpenAPI export adds a security scheme only to routes that use it; none do, so no diff. Check with `--export-openapi --check`.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker or `TEST_DATABASE_URL` needed by the older tests; the new one needs neither), `uv run python -m app.cli --export-openapi --check`. Anything not run goes under "Not verified".

## Docs (same PR, rule E1)
- [ ] docs/features/POC-4.4/spec.md (ACs checked off)
- [ ] docs/ARCHITECTURE.md — `security.py` and the dependencies built, `pyjwt` runtime dependency, JWT settings
- [ ] docs/RUNBOOK.md — the four settings; `development` and `production` refuse to boot without real secrets (so `.env.development.example` needs editing before use)
- [ ] docs/api/ENDPOINTS.md — Authentication section: the dependency behaviour, 401 header; docs/api/ERRORS.md only if wording changes
- [ ] DOMAIN_GLOSSARY: no new term; ADR: none (inside ADR-0008/0010)

## Risks and unknowns
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Q1 boot rule breaks existing tests that build `Settings()` with `APP_ENV=production` | red tests | grep tests for `app_env`; R1 run of the full unit suite |
| Weak default secret ends up in a real deploy | auth bypass | no default exists; the 32-char rule in non-local envs |

## Estimate
R1 S, R2 M, R3 M.

## Not covered
Database lookup of the account, refresh-hash comparison, roles, routes, token issue on sign-in, cookies, rate limiting.
