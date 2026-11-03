# POC-5.5 — Admin seed and development customers

## Problem
A fresh database has the two roles (task 5.1) and nothing else: no account can be used to try the API. The Node base seeds one admin
(`InitAdminMigration`, `assets/admins.ts`) and, outside production, three sample customers (`InitCustomerMigration`, `assets/customers.ts`).
Task 5.4 is merged, so the profile update the Node items call exists here.

## Goal / business value
Goal 1 (a fork starts with a usable local database) and goal 3 (the test template gets real accounts to log in as, once 7.x lands).

## Scope
- in: seed items `init.admin` (`app/seeds/items/init_admin.py`) and `init.customer`
  (`app/seeds/items/init_customer.py`), both in the development list (`local`, `development`, `test`), the admin first; the sample data as constants in those modules; the registry; the docs.
- **out (explicit):** password hashes for the sample customers (the Node `password` field is not used by Node either and bcrypt arrives with 7.3, no new
  dependency, rule C2), any sign-in route (7.x), `SSN` (ADR-0015), real client data, any production admin (a fork adds its own seed with its own phone).

## Acceptance criteria
- [ ] AC1 Given a migrated, empty database, when the seed runner runs the registry for `local`, then the database holds 2 roles, 1 admin account and 3 customer accounts.
- [ ] AC2 Given a second run (or a second boot), then nothing is added and `SeedHistory` has one successful row per item.
- [ ] AC3 The admin holds the `ADMIN` role and not `CUSTOMER`; each customer holds `CUSTOMER` only. The admin check is by role type through the join, never by comparing a role id with the string `ADMIN` (issue I.4).
- [ ] AC4 Each account has a live profile with the sample names, and the customers also their email, middle name and date of birth, written through `AccountProfileService.update` (so they are validated and normalised like a request).
- [ ] AC5 `init.customer` runs even though the admin account already exists (Node's `account.count() === 0` check made it a no-op after the admin seed), and creates only the sample phones that are missing.
- [ ] AC6 `production` gets the roles only; `local`, `development` and `test` get all three items, in the order roles, admin, customer.
- [ ] AC7 Every sample phone is a valid number for the `PhoneNumber` type of task 4.3 and every sample email a valid `ProfileEmail`, so each seeded account can use OTP and profile routes (a unit test proves it).
- [ ] AC8 A failing item is recorded in `SeedHistory` and stops the boot, as for `init.roles` (unchanged runner behaviour, tested with the new items).

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Admin already exists (a fork added its own) | `init.admin` does nothing | Node `inNeedToRun`, fixed to compare role types (I.4) |
| One sample customer already exists (same phone) | the others are still created; none is duplicated | AC5 |
| Sample email already used by another profile | the unique index fails the item: recorded, boot stops (rule D5) | runner |
| Roles missing (item order broken) | `RoleNotFoundError`, recorded, boot stops | 5.2 |
| The admin's phone | `+12125550100`, valid for `phonenumbers` and in the NANP range reserved for fiction (555-0100 to 0199), so it never belongs to a real person; Node used `+11111111111`, which `phonenumbers` rejects, so that admin could never request an OTP | decided by the human in session |

## Open questions
| # | Question | Assumed answer | Needs a human? |
|---|----------|----------------|----------------|
| Q1 | Admin phone | reserved fictional number `+12125550100` | decided, see above |
| Q2 | Seed names | `init.admin` and `init.customer`, the Node names without the `.migration` suffix, as `init.roles` | no |
| Q3 | Does production get the sample admin? | **No (decided by the human in session)**: the admin is in the development list only; a difference from Node, where it was in the base list | resolved |
| Q7 | Sample customer values | fictional, not Node's: phones `+1212555010x`, emails `customer+dN@example.com` | no |
| Q5 | The admin's last name | Node used `Trukkit`, another project's name; the base keeps client-specific names out (BUSINESS_MODEL), so `Admin` / `User` | no |
| Q6 | May `seeds` import `schemas`? | **Yes, for `seeds` only (decided by the human in session)**, recorded in ADR-0023; needed to call `AccountProfileService.update`. `workers` are not covered | resolved |
| Q4 | Sample customers have no password identity | as in Node (the `password` field is unused there); they sign in by OTP | no |
