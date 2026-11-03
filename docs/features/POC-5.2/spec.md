# POC-5.2 — AccountRoleService and require_roles

## Problem
Nothing can say what roles an account holds, give an account a role, or refuse a route to the wrong role. Task 4.4 authenticates a token
and stops there; task 5.4 (`PATCH /accounts/{accountId}/profile`) needs the second layer of rule P7 (authenticate, then role, then ownership).
The Node base does this with `AccountRoleService` and `RoleGuard` (`auth/guards/role.guard.ts`).

## Goal / business value
Goal 2 (authentication: roles are part of the pipeline a new POC relies on as-is) and goal 1 (a reusable guard a fork applies to its own routes).

## Scope
- in: `AccountRoleService` (`get_account_roles`, `add_account_to_role`) in `app/services/account_role.py`; `require_roles(*roles)` in
  `app/dependencies.py`, a dependency factory that runs `current_account`, loads the caller's roles and answers 403 `FORBIDDEN` when none matches.
- **out (explicit):** any real route using the guard (5.4 and later), loading or rejecting a deleted account (5.3), role assignment at sign-up (7.x),
  admin screens or role-management endpoints, a read cache for roles (9.2), the ownership layer (5.4), changing `AccountRoleType`.

## Acceptance criteria
- [ ] AC1 Given a customer's token, when a route declared with `require_roles(ADMIN)` is called, then 403 `FORBIDDEN` with the standard error body.
- [ ] AC2 Given an admin's token on that route, then the handler runs and receives the caller's `TokenClaims`; `require_roles(ADMIN, CUSTOMER)` admits either role.
- [ ] AC3 Given no token, or a bad one, then 401 `UNAUTHORIZED` (from `current_account`), never 403.
- [ ] AC4 Given a valid token whose account holds no role, then 403.
- [ ] AC5 `get_account_roles` returns the role types of the account's links; a soft-deleted link or a soft-deleted role is not counted (rule P6).
- [ ] AC6 `add_account_to_role` links the account to the role by type; an unknown role type raises `RoleNotFoundError` (a 500, not swallowed, as Node's `Error`).
- [ ] AC7 `require_roles()` with no roles raises `ValueError` when the route is declared (fail closed; Node logged and let the request through).
- [ ] AC8 `openapi.json` is unchanged (`--export-openapi --check` passes).

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Account has both roles | any match admits | Node `intersection` |
| Link exists but `deleted` is true | not a role of the account | rule P6 (Node did not filter; a stated difference) |
| Same account and role added twice | the primary key rejects it; `IntegrityError` propagates | assumption Q2 |
| Token valid but account row deleted or missing | roles come back empty, so 403; the account check is 5.3 | scope |
| Database not configured | `get_session` fails as for any route needing one | existing behaviour |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Does the service commit? | No: it flushes, the caller (route or test) owns the transaction, as `get_session` never commits | no |
| Q2 | Re-adding a soft-deleted link: revive it? | No; out of scope, no caller yet. The error is not swallowed | no |
| Q3 | Filter soft-deleted links, which Node does not? | Yes, rule P6 and the glossary say "delete" means the flag | no |
