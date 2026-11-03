# ADR-0023 — `seeds` may import `schemas`

- **Date:** 2026-11-03
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-5.5
- **Supersedes:** one clause of ADR-0011 rule 4 ("`workers` and `seeds` use services, models, core and config"), for `seeds` only. `workers` are unchanged.

## Context
Task 5.5 seeds an admin and three sample customers. The Node base wrote their profiles through `updateAccountProfileService`, so the sample values were
checked and normalised like a request. Here that is `AccountProfileService.update(caller_id, account_id, changes)`, and `changes` is a Pydantic request
model, `UpdateAccountProfileInput`, which lives in `app/schemas/`. ADR-0011 lets `seeds` import services, models, core and config, so a seed item
cannot build that argument.

## Decision
- A module in `app/seeds/` may import from `app/schemas/`, as `services` already may (ADR-0011 rule 4: schemas are plain data).
- Nothing else changes. `schemas` still import nothing from `services`, `models` or `routers`; `workers` keep the list of ADR-0011, and the worker task (6.x)
  raises its own question if it needs `schemas`.
- `.claude/rules/project-structure.md` rule 4 is updated to match; ADR-0011's body is left as written and its Status line points here.

## Consequences
- Seed data goes through the same validation as an API request, so a sample email or date that the API would refuse fails the seed (recorded in
  `SeedHistory`, rule D5) instead of landing unchecked in the database.
- Seeds depend on request models: a change to `UpdateAccountProfileInput` can break a seed item. A test builds every sample value through it (task 5.5).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Seed items set the profile columns on the models directly | the sample email, phone and date would be unchecked and not normalised; it also repeats the update logic of `AccountProfileService` |
| Move `UpdateAccountProfileInput` into `core/` | a request model of one module is not cross-cutting code; it would blur the layer boundary instead of stating the exception |
