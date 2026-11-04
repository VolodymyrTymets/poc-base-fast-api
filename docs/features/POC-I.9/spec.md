# POC-I.9 — One Depends provider per service

## Problem
A route builds its service by hand (`AccountProfileService(session, FileAssertService(session, settings))` in `app/routers/account_profile.py`,
`AccountService(session)` in `routers/account.py`, `AccountRoleService(session)` inside `require_roles`). Every route repeats the wiring and a test cannot swap a
service through `app.dependency_overrides`. Package 7 adds six auth routes; they should start on providers, not copy the wiring.

## Goal / business value
Goal 1 (scaffolding: easy to fork and extend) and goal 3 (test base: a service can be replaced in an HTTP test). Behaviour does not change.

## Scope
- in: one provider per service in `app/dependencies.py` (`get_account_service`, `get_account_role_service`, `get_file_assert_service`, `get_account_profile_service`), each taking
  `get_session` (and `app_settings` where needed) so one request shares one session; every existing route and `require_roles` use them; routes keep the commit (ADR-0021);
  an ADR extending ADR-0021; a new rule file `.claude/rules/routes-convention.md`; `project-structure.md` and `ARCHITECTURE.md` follow.
- **out (explicit):** any behaviour change; services' constructors and signatures; `get_queue` and the token dependencies (already providers); `openapi.json` content;
  moving `session.commit()` out of the route; a repository layer; the scope doc's own status column (a local untracked file, noted in the PR body).

## Acceptance criteria
- [x] AC1 No file in `app/routers/` constructs a service class; each route takes `Annotated[XService, Depends(get_x_service)]`.
- [x] AC2 `require_roles` gets its `AccountRoleService` through `Depends(get_account_role_service)`.
- [x] AC3 Within one request the guard, the service and the route's `session` are the same `AsyncSession` (the commit in the route persists what the service flushed).
- [x] AC4 A test overrides a provider with `app.dependency_overrides[get_account_service]` and the route uses the fake.
- [x] AC5 `uv run python -m app.cli --export-openapi --check` exits 0 with `openapi.json` unchanged; the existing HTTP tests pass untouched.
- [x] AC6 A unit test fails when a router module constructs a service (the convention is enforced, not only written).
- [x] AC7 ADR-0025 (extends ADR-0021), `.claude/rules/routes-convention.md`, `project-structure.md` and `ARCHITECTURE.md` updated.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Unauthenticated request with no database | still 401 (claims dependency listed before the session-based ones) | existing tests `test_http_account.py`, `test_http_require_roles.py` |
| Guard and route both depend on `get_session` | FastAPI caches it per request: one session | AC3 test |
| Provider needs another provider (`get_account_profile_service` -> `get_file_assert_service`) | declared with `Depends`, so either can be overridden | this plan |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| 1 | The ticket says `routs-convention.md`; no such file exists | create `.claude/rules/routes-convention.md` (path-scoped to `app/routers/**`); `.claude/**` is ask-first, so approval of this plan is the confirmation | yes, name and creation |
| 2 | ADR number | ADR-0025 (last is 0024) | no |
| 3 | Ticket ID | `POC-I.9`, branch `chore/POC-I.9-service-providers` | no |
