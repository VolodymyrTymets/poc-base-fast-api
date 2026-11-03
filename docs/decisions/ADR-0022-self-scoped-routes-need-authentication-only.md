# ADR-0022 — A self-scoped route needs authentication only; rule P7's role layer is "any authenticated account"

- **Date:** 2026-11-03
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-5.3
- **Supersedes:** nothing. It settles ENDPOINTS mapping decision 15, which left it to a human.

## Context
Rule P7 asks for three layers on a guarded route: authenticate, role, per-record ownership. `GET /api/v1/account` returns the caller's own account, and the
Node base put no role guard on it. The analyze gate of POC-5.3 asked for a human answer: require `CUSTOMER` or `ADMIN` (literal P7), or keep the Node behaviour.

## Decision
- A route whose record is chosen by the token (`GET /account`, and later sign-out and change-password) has its role layer satisfied by "any authenticated
  account". It declares `Depends(current_account)` and no `require_roles`. Ownership holds by construction: the id comes from the token, never from the path or body.
- A route that takes another record's id (`PATCH /accounts/{accountId}/profile`, files) keeps all three layers, and checks ownership in the service.
- A valid token whose account is missing or soft-deleted is 401 `UNAUTHORIZED` on these routes, with the Bearer challenge (ENDPOINTS decisions 2 and 16).

## Consequences
- An account with no role can read its own account. A fork that wants otherwise adds `require_roles(...)` to the route; the 5.2 guard lets a missing account through
  to the 401 only if the account lookup runs first, so the check order would need care.
- Only this route rejects a deleted account today; `current_account` still verifies the token alone.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `require_roles(CUSTOMER, ADMIN)` on every route | a role-less account could not read itself, and a missing account would answer 403 instead of the specified 401 |
