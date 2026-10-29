# POC-1.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving confirms the decision table in spec.md as written (edit the table first to change an answer),
     and the line must name D5, D6 and D7, which need an explicit yes (rule F2), and the ranked goals. Format:
     Approved-by: volodymyr · <date> — D5 yes, D6 yes, D7 yes, goals confirmed, one-day size ok
     (rule F2: about 8 ADRs plus docs is roughly a working day; to split, make R1–R5 one PR and R6–R9 a second) -->
Approved-by: volodymyr · 2026-10-29 — D5 yes, D6 yes, D7 yes, goals confirmed, one-day size ok (stated in chat; written here by Claude at the user's instruction)

Pattern followed: `docs/decisions/ADR-0001-uv-dependency-manager.md` and `ADR-0002-python-3-14.md` (this repo's two
ADRs, written from `docs/decisions/ADR-000-template.md`). Supersession wording follows the Node base's ADR-0010
(`/Users/work/Documents/projects/poc-base/docs/decisions/ADR-0010-postgres-file-storage.md`), which names what it
replaces and lists rejected alternatives. Layer: documentation only.

## Contract changes
- boundary: none (no code). The ADRs *decide* the future boundary: REST under `/api/v1` replaces GraphQL.
- data: none. ADR-0008 records that a future Python API on a Node-written database logs out every session (D5).
- generated output: none.

## Requirements (ordered, each independently verifiable, one commit each)

Work happens on one branch, `feat/POC-1.1-decisions-adrs`, delivered as one draft PR (rule A4).

Every ADR requirement R1–R8: file `docs/decisions/ADR-00NN-<slug>.md` (new), layer docs, executed how = run the
checks, then `uv sync && uv build` unchanged. Checks per file, each printing the stated count (the unfilled template
fails the first four, so placeholders cannot pass):
- `grep -c -E '^- \*\*Date:\*\* 2026-[0-9]{2}-[0-9]{2}$'` = 1
- `grep -c -E '^- \*\*Status:\*\* accepted$'` = 1; `grep -c -E '^- \*\*Deciders:\*\* volodymyr$'` = 1; `grep -c -E '^- \*\*Ticket:\*\* POC-1\.1$'` = 1
- `grep -c -E '^## (Context|Decision|Rejected alternatives|Consequences|Revisit when)$'` = 5
- `grep -c '^| Alternative | Why not |$'` = 1 and at least one data row below it (AC2)
- `grep -c -E '([Ss]upersedes|[Aa]mends)'` >= 1 (AC3), and the `Node ADR-NNNN` grep named in each requirement >= 1
- Numbering clash guard: the Node repo has ADR-0001…0012 too, so every cross-repo reference is written `Node ADR-NNNN (<title>)` and a bare `ADR-00NN` always means this repo. Check: `grep -n -E '(^|[^e] )ADR-00[0-9]{2}' <file>` lists only this repo's own ADRs
Evidence (rule B5): the real output of these commands, pasted into the PR body.

### R1 — ADR-0003 REST API with FastAPI and OpenAPI (S)
- D2. "Supersedes Node ADR-0002 (GraphQL-first API) and Node ADR-0003 (Pass GraphQLResolveInfo into services)"; greps `Node ADR-0002`, `Node ADR-0003`. Records: `/api/v1`, Pydantic models never ORM objects, the contract exported to a root `openapi.json` (this repo's layout ADR-0010 has no `api/`) with a stale-spec test, error body `{"error": {"code","message","details"}}`, fixed response shapes (no field selection). Rejected: keep GraphQL (Strawberry), REST without a contract.

### R2 — ADR-0004 Data layer: SQLAlchemy 2 async + Alembic (M)
- D3. "Supersedes the ORM half of Node ADR-0001 (Use Prisma as the ORM, with a Redis-backed read cache)"; the cache half stays open until task 9.1; grep `Node ADR-0001`. Records: same table and column names as a target proven by task 2.5, quoted identifiers, soft-delete mixin. Rejected: Prisma Client Python (the scope doc calls it unmaintained; cite the source or state it as the scope doc's claim), SQLModel, Tortoise.

### R3 — ADR-0005 Job queue: arq (S)
- D4. "Supersedes Node ADR-0005 (BullMQ background jobs as a separate Nest application)"; grep `Node ADR-0005`. Records: separate worker process; `max_tries` set on the worker (default 5); backoff is **not** a setting, it is raised per job as `Retry(defer=ctx['job_try'] * n)` (confirmed with Context7, arq docs); `QueueClient` protocol injected into notifiers. Rejected: Celery, Dramatiq, FastAPI BackgroundTasks (not durable).

### R4 — ADR-0006 Test database: testcontainers PostGIS template (S)
- D8. "Supersedes none: replaces the PGlite convention in Node `CLAUDE.md` P5, which has no ADR number"; grep `PGlite`. Records: container once per session, `CREATE DATABASE … TEMPLATE` per module, `TEST_DATABASE_URL` escape hatch, Docker needed. Rejected: PGlite (no Python driver), SQLite, mocked sessions (violates rule P8).

### R5 — ADR-0007 Quality tooling: ruff, mypy strict, pytest (S)
- "Supersedes Node ADR-0007 (Oxlint replaces ESLint as the linter)"; grep `Node ADR-0007`. Records the tool set and ruff rule families (B, S, ASYNC, T20); installation is POC-1.4, not here; uv itself is ADR-0001. Rejected: black+flake8+pylint, pyright.

### R6 — ADR-0008 Auth tokens: sha256 refresh hash and header transport (M)
- D5, D6. "Supersedes none; amends Node ADR-0004 (JWT access/refresh auth with OTP sign-in) and Node ADR-0011 (Email + password auth)", closing Node ADR-0011's refresh-token item; rate limiting and email-change items stay open (out of scope); grep `Node ADR-0011`. Records: store sha256(refreshToken); bcrypt >= 5 raises `ValueError` over 72 bytes (confirmed with Context7, pyca/bcrypt); `x-refresh-token` header on `POST /api/v1/auth/refresh`; cookie option deferred. Rejected: bcrypt of base64(sha256) (the library's own workaround: works, but a slow hash adds nothing for a high-entropy token), raw JWT storage, httpOnly cookie now. Extra checks: `grep -c '72 bytes'` >= 1.
- Precondition: `Approved-by:` says "D5 yes, D6 yes" (auth, rule F2).

### R7 — ADR-0009 File transfer: multipart and authenticated download (S)
- D7. "Supersedes Node ADR-0010 (PostgreSQL replaces S3 for file storage) in transport only; storage stays Postgres"; grep `Node ADR-0010`. Records: `POST /api/v1/files`, `GET /api/v1/files/{id}/content`, bytes in Postgres `bytea`, 10 MB cap; consequence: not usable in `<img src>` without a blob fetch or signed URL. Rejected: base64 JSON, object storage.
- Precondition: `Approved-by:` says "D7 yes" (contract).

### R8 — ADR-0010 Repo layout and configuration (S)
- D1, D9, D10. "Supersedes Node ADR-0008 (web app scaffold) and Node ADR-0012 (web auth client), since this repo has no `web/`; amends Node ADR-0009 (configurable ports): only the env names carry over, compose and `set-ports.sh` are task 11.2"; grep `Node ADR-0008`. Records: root-level `src/poc_base_fast_api/` package, API only; `APP_ENV` replaces `NODE_ENV`; env names kept; one `JWT_SECRET` (closes Node issue I.1); pydantic-settings validated at boot. Rejected: `api/` subdirectory (no second workspace to separate), copying `web/`.

### R9 — Close the decision table; update ARCHITECTURE.md, BUSINESS_MODEL.md, CLAUDE.md (S)
- files: `docs/features/POC-1.1/spec.md` (change: Outcome column becomes `accepted` or `changed (<what>)` per the approval line; open question 3 marked answered), `docs/ARCHITECTURE.md` (change: the Status line is rewritten (it still says D1–D10 are not confirmed); the ORM, REST, queue, test-DB, layout and file items move from "Planned" to "Decided" with ADR links, while the Redis read cache and the packages-by-feature bullet stay under "Planned" (task 9.1 decides the cache); `api/openapi.json` becomes root `openapi.json`; the two landmines are reworded, not deleted: "the scope doc still says 3.12 and `api/`; ADR-0002 and ADR-0010 win"), `docs/BUSINESS_MODEL.md` (change: drop "confirm or re-rank when task 1.1 runs"), `CLAUDE.md` (change: only the second sentence of P2 — the one saying D1–D10 are unconfirmed — is replaced by "decisions D1–D9 are recorded in ADR-0003…0010; a change needs a superseding ADR"; the first sentence, "Do the work in the doc's order and honour its dependency lines", stays; ask-first path, the hook will ask).
- test: `grep -c "assumed accepted" docs/features/POC-1.1/spec.md` = 0; `wc -l < CLAUDE.md` < 200; `grep -c "doc's order" CLAUDE.md` = 1; `grep -n -i -E "unconfirmed|not confirmed|api/openapi" docs/ARCHITECTURE.md` empty; `grep -c "confirm or re-rank" docs/BUSINESS_MODEL.md` = 0; `git diff --stat main` touches only `docs/` and `CLAUDE.md`.

## Docs to update in this PR
- [x] docs/features/POC-1.1/spec.md (acceptance criteria checked off, outcome column closed)
- [x] docs/ARCHITECTURE.md, docs/BUSINESS_MODEL.md, CLAUDE.md — R9
- [x] docs/DOMAIN_GLOSSARY.md — none expected (refresh-token row already says sha256)
- [x] docs/decisions/ADR-0003 … ADR-0010 — R1–R8

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| 3.14 lacks wheels for the planned stack | ADR-0002 would block every dependency | Done: `uv pip compile --python-version 3.14 --only-binary :all:` resolved fastapi, sqlalchemy 2.1, asyncpg, pydantic-core, arq, bcrypt 5, testcontainers, ruff, mypy |
| Library claims in ADRs are wrong (arq backoff, bcrypt limit) | a false rationale | Done for arq and bcrypt (Context7); re-check any new claim before writing it, cite the source in the ADR |
| Prisma-name compatibility is claimed before it is proven (ADR-0004) | wrong "same names" promise | ADR says "target", proven by task 2.5 |
| Scope doc keeps saying `api/`, 3.12, ADR-P0x | later tasks follow stale text | ARCHITECTURE landmines point at the ADRs; PR body lists the scope-doc lines to edit |

## Assumptions
- Numbering continues at ADR-0003; ADRs are `accepted` because approving this plan confirms the decision table. No ADR is written before approval.
- The Node repo is read-only for us; supersession is stated in the new ADRs only.
- Size: about a working day in one PR (rule F2); approval with "one-day size ok" accepts that, otherwise split as noted in the approval comment.
- No tracker: ticket = `POC-1.1`. Estimates: R1–R8 S/M each (about one hour per ADR), R9 S.
- Checked while planning: Node ADR numbers and titles match `poc-base/docs/decisions/`.
