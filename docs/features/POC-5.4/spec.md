# POC-5.4 — PATCH /api/v1/accounts/{accountId}/profile

## Problem
A signed-in account cannot change its profile. Node has `updateAccountProfile` (`account-profile/account-profile.resolver.ts`,
`account-profile.service.ts`): three layers (token, role `ADMIN`/`CUSTOMER`, the caller owns `accountId`), an avatar the caller owns, an email stored
normalised, and 409 on a duplicate. The request model exists (task 4.3), `FileAssertService` is merged (8.1), `AccountProfileResponse` exists (5.3).

## Goal / business value
Goal 2 (authentication pipeline: a profile with a unique, normalised login email is what password sign-in looks up) and the first route that uses all three
layers of rule P7, which forks copy.

## Scope
- in: `AccountProfileService` (`get_by_account_id`, `update`); `PATCH /api/v1/accounts/{accountId}/profile` returning `AccountProfileResponse`;
  regenerated `openapi.json`.
- **out (explicit):** the read-cache invalidation hook (task 9.2 owns the cache and adds it where it writes), `GET` of a profile (not in the endpoint map),
  creating a profile, uploading the avatar file (8.2), email change without re-authentication (issue I.8, carried over), SSN and `is18YearOld` (ADR-0015),
  rejecting a soft-deleted account in the other guarded routes.

## Acceptance criteria
- [ ] AC1 Given the caller's own id and `{"firstName": "Jane", "email": "Jane@Example.com"}`, then 200 with the updated profile, and the stored email is `jane@example.com`.
- [ ] AC2 Fields that are not sent stay unchanged; an explicit `null` clears a nullable one (`avatarId: null` removes the avatar); `email: null` is 422 (task 4.3).
- [ ] AC3 Given another account's id in the path, then 403 `FORBIDDEN`, answered by the service before the profile or any file is read or written (the role check of `require_roles` comes first, rule P7); no token is 401, an account with no role is 403.
- [ ] AC4 Given the caller's id but no live profile (or a soft-deleted profile or account), then 404 `NOT_FOUND`.
- [ ] AC5 Given an `avatarId` of a file the caller did not create, an unknown file or a soft-deleted one, then 403 `FORBIDDEN` and nothing is written; an owned file is accepted.
- [ ] AC6 Given an email another profile already has (any case, including a soft-deleted account's), then 409 `EMAIL_ALREADY_REGISTERED`, the profile is unchanged and the request's session is still usable.
- [ ] AC7 An unknown key (for example `SSN`, `is18YearOld`) is 422 `VALIDATION_FAILED` (task 4.3's `extra="forbid"`).
- [ ] AC8 The change is committed: a following `GET /api/v1/account` shows it.
- [ ] AC9 `openapi.json` is regenerated and the stale test passes; the response holds no ORM class and no identity data.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Empty body `{}` | 200, nothing changes, the current profile is returned | Node (an empty update is a no-op) |
| Same email as the caller's own | 200 (no conflict with itself) | unique index only conflicts with another row |
| Email differs only by case from another's | 409 (stored lowercase, compared lowercase) | Node spec "ignoring case" |
| Another caller of `AccountProfileService.update` (not the route) | the service itself refuses with `ForbiddenError` when the ids differ | rule P7, ownership in the service |
| Soft-deleted account with a live role link | 404 (its profile is not live for it); not 401 | assumption Q1 |
| `avatarId` of a file the caller owns that is later deleted | the FK keeps pointing at it; reading it is 8.2's filter | models note |
| Two concurrent updates to one email | one wins, the other 409 through the unique index | AC6 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | A soft-deleted account that still holds a role link passes `require_roles`; what does PATCH answer? | 404 `NOT_FOUND` (no live profile for it). A uniform 401 for deleted accounts on every guarded route is a separate change (ENDPOINTS decision 16, still open for refresh), not slipped in here **decided by the human in session: 404**; unknown account stays 403 from `require_roles` | resolved |
| Q2 | Cache invalidation hook (scope doc row 5.4)? | Not built: no cache exists; 9.2 adds invalidation where the service writes | no |
| Q3 | The Node spec cases | Ported where they apply; see the table in plan.md | no |
