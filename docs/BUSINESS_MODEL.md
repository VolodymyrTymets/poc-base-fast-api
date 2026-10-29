# Business model

> Why this product exists. This file is the **tie-breaker** the agent uses when two technically valid options collide.
> Goals must be **ranked** — an unranked list gives no way to decide.

## What this product is
`poc-base-fast-api` is an internal starter kit for spinning up future client POC projects quickly, rebuilt on
Python + FastAPI with a REST API. It is the Python counterpart of the Node/GraphQL `poc-base` and is not a
customer-facing product. It provides the pieces a new POC would otherwise rebuild: password and OTP
authentication with JWT access/refresh tokens, roles, file storage in Postgres, seed data, a background
worker, a Redis read cache and a real-database test base.

The work plan is the doc "Scope Breakdown: poc-base on Python + FastAPI (REST)" (49 tasks, about 175 h).
Status today: only the `uv init` skeleton exists; nothing in that plan is built yet.

## Ranked goals
Carried over from `poc-base`; confirmed by volodymyr on 2026-10-29 (POC-1.1).
1. **Project scaffolding** — the base stays easy to fork and reuse as the start of a new POC.
2. **Authentication** — a working, understandable auth pipeline (OTP sign-in, JWT access/refresh, roles) a new POC can rely on as-is.
3. **Test base** — a real-database test setup that keeps working and is easy to extend.

## Non-negotiables (never trade these for speed)
- No tokens, passwords, SSN, DOB or phone numbers in logs.
- Refresh tokens are stored as a sha256 hash, never as bcrypt of the whole JWT.
- Tests use a real Postgres, never a mocked database.
- Soft deletes only on domain tables.

The Node base also had "real SMS/email must be used", relaxed for the POC stage: workers only log. That
carries over unchanged — log-only is accepted until a ticket wires a provider.

## Explicitly out of scope (this phase)
- New domain endpoints beyond the Node base, and admin screens.
- A real SMS or email provider (still log-only).
- Rate limiting, email verification, httpOnly-cookie refresh tokens.
- Staging or production deployment — no environment is defined.
- A GraphQL endpoint alongside REST.
- `web/` — this repo is the API only.

## Judgement examples
| Situation | Decide this way | Because |
|-----------|-----------------|---------|
| A feature that is generic vs. one aimed at a hypothetical client | Build the generic one; keep client logic out | goal 1 |
| Polish the seed data vs. ship the next scaffolding piece | Ship the scaffolding piece | goal 1 over goal 3 |
| A quick fix by mocking the database in a test | Fix it against a real Postgres | non-negotiable |
| Port a Node behaviour exactly vs. fix a known Node issue | Fix it if the scope doc lists the issue (I.1–I.8), otherwise keep the behaviour | the doc is the plan |

## Soft values
A new POC should be clonable and understandable in under a day. Favour obvious, conventional patterns over
clever ones: whoever forks this next did not write it.
