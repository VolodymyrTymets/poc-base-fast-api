# POC-1.1 — Confirm decisions D1–D10 and record them as ADRs

## Problem
The scope doc ("Scope Breakdown: poc-base on Python + FastAPI (REST)") is written for ten assumed decisions (D1–D10).
Until each is confirmed and recorded, rule P2 in `CLAUDE.md` forbids building on them, so every later task is blocked.
The Node ADRs they replace (GraphQL, Prisma, BullMQ, PGlite tests, bcrypt refresh tokens) are still the only written
record, and they contradict the new direction.

## Goal / business value
Goal 1 (project scaffolding): a fork must be able to read why the base is built this way. Goal 2 (authentication):
D5 changes how refresh tokens are stored, which is a security decision that needs a named human decider (rule F2).

## Scope
- in: one ADR per decision group (list in plan.md), each naming the Node ADR it supersedes; update `ARCHITECTURE.md`
  "Planned" into "Decided" with links; update `CLAUDE.md` rule P2 to point at the ADRs; drop the "confirm or
  re-rank" line in `docs/BUSINESS_MODEL.md` (approval confirms the ranked goals); record D1–D10 outcomes
  in the table below.
- **out (explicit):** any code, dependency or `pyproject.toml` change (ruff, mypy, pytest, FastAPI arrive in
  POC-1.3/1.4); the endpoint map (1.2); editing the Node repo; editing the scope doc's task statuses
  (the human does that); `web/` and decision D10 (no web in this repo).

## Acceptance criteria
- [x] AC1 Given D1–D10, when the PR is reviewed, then each has an outcome in the decision table: accepted, changed, or dropped (D10).
- [x] AC2 Each new ADR uses the template, has Status `accepted`, Deciders `volodymyr`, Ticket `POC-1.1`, a Rejected-alternatives table and a "Revisit when".
- [x] AC3 Each ADR names the Node ADR(s) it supersedes by number and title, or says it supersedes none.
- [x] AC4 The D5 ADR states the security reason (bcrypt >= 5 rejects input over 72 bytes) and closes the refresh-token part of Node ADR-0011's risk list.
- [x] AC5 `docs/ARCHITECTURE.md` no longer says "unconfirmed" for decided items and links each ADR; the 3.12-vs-3.14 and `api/`-vs-root landmines are resolved or removed.
- [x] AC6 `CLAUDE.md` rule P2 is reworded (decisions now recorded) and the file stays under 200 lines.
- [x] AC7 `uv sync` and `uv build` still pass, and no file outside `docs/` and `CLAUDE.md` changed (`git diff --stat`).

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| A decision is changed by the human during approval | the ADR records the changed answer; the scope doc is flagged as stale in the PR body | volodymyr |
| The scope doc says `api/` or Python 3.12 | the ADR wins; the PR body lists the scope-doc lines to update | ADR-0002, D1 |
| Redis cache (Node ADR-0001, second half) | ADR-0004 supersedes only the ORM half; the cache is decided in task 9.1 | this plan |

## Decision table (outcomes the human confirms by approving plan.md)
| D | Decision | Outcome | ADR |
|---|----------|---------|-----|
| D1 | Python lives in this repo, root-level package, API only | accepted (answered in chat) | 0010 |
| D2 | REST with FastAPI + Pydantic under `/api/v1`, `openapi.json` is the contract | accepted | 0003 |
| D3 | SQLAlchemy 2 async + asyncpg + Alembic, Prisma table/column names | accepted | 0004 |
| D4 | arq for the job queue, separate worker process | accepted | 0005 |
| D5 | Refresh token stored as sha256, not bcrypt (**security: needs explicit yes**) | accepted, explicit yes 2026-10-29 | 0008 |
| D6 | `x-refresh-token` header on `POST /api/v1/auth/refresh` | accepted, explicit yes 2026-10-29 | 0008 |
| D7 | Multipart upload + authenticated download, bytes stay in Postgres (**needs explicit yes**) | accepted, explicit yes 2026-10-29 | 0009 |
| D8 | testcontainers `postgis/postgis:16-3.4`, template DB per run | accepted | 0006 |
| D9 | `NODE_ENV` becomes `APP_ENV`; keep `DATABASE_URL`, `REDIS_*`, `PORT`, `JWT_*`, `CORS_ORIGINS`, `FILE_*`; one `JWT_SECRET` | accepted | 0010 |
| D10 | web REST client | **dropped**: no `web/` in this repo | — |
| — | ruff + mypy strict + pytest (+ pytest-asyncio); installed in POC-1.4 | accepted | 0007 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| 1 | ADR numbers: the scope doc says `ADR-P01…P08`; the repo numbers sequentially | continue at ADR-0003 | no |
| 2 | Are D2–D4, D6, D8, D9 acceptable as written? | yes | answered: approved 2026-10-29 |
| 3 | D5 and D7: explicit yes? | yes | **yes** (security / contract) — answered by writing "D5 yes, D7 yes" in plan.md's `Approved-by:` line, before implementation |
