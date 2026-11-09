# POC-11.5 — Docs, rules and the CLAUDE.md map

## Problem
Most of what row 11.5 lists was written task by task, so what exists is correct in parts and stale in others:
- `README.md` is empty (0 bytes); a new developer has no entry point.
- `docs/BUSINESS_MODEL.md` says "only the `uv init` skeleton exists; nothing in that plan is built yet" and "49 tasks, about 175 h"; `docs/ARCHITECTURE.md` still says "Status: skeleton with decisions recorded".
- The `CLAUDE.md` command map has no row for the compose stack, the CI-equivalent commands (`pytest -m "not e2e"`, `uv sync --locked`) or the port and env scripts.
- `.claude/rules/` has no file for the two stack areas the scope row names, FastAPI/SQLAlchemy backend conventions and the REST contract; their content is spread over ADR-0003, 0021, 0025, 0027, `docs/api/*` and `routes-convention.md`.
- Some partly superseded ADRs do not say so in their status line.
- The RUNBOOK has never been followed from a clean clone as a stranger would.

## Goal / business value
Goal 1 (scaffolding): the base is clonable and understandable in under a day (BUSINESS_MODEL soft value), and a forked POC finds the rules where the agent will load them.

## Scope
- in: audit and fix of the docs named above; `README.md` (short: what it is, first run, where the docs are); two new rule files, `.claude/rules/backend-fastapi.md` and `.claude/rules/api-rest.md`, each only restating decided ADRs with their numbers; `CLAUDE.md` command map rows and the stale "ADR-0003 to ADR-0010" pointer; superseded-ADR status lines; a stale-doc sweep of ARCHITECTURE, BUSINESS_MODEL, DOMAIN_GLOSSARY, RUNBOOK; following the RUNBOOK on a clean clone.
- **out (explicit):** any code, test or workflow change; new decisions (a rule file restates, never decides: a gap becomes a follow-up, not an ADR here); the scope doc itself (a Claude Docs document outside the repo: its statuses are listed in the PR body); `web/`; rewriting ADRs (only status lines).

## Acceptance criteria
- [ ] AC1 Given a clean `git clone` and only the RUNBOOK, when its first-run steps are followed (uv path and the Docker Compose path), then the API answers `/api/v1/health` and the OTP flow reaches the worker log; any step that failed or was missing is fixed in the RUNBOOK (evidence: the commands run in a scratch clone).
- [ ] AC2 `README.md` is non-empty, under 60 lines, and every command in it is a command-map row or a RUNBOOK section it links to.
- [ ] AC3 `CLAUDE.md` stays under 200 lines; its command map lists every command a developer or CI runs (compose up/down, the CI test selection, `uv sync --locked`, the two scripts); `P2` points to the current ADR range.
- [ ] AC4 `backend-fastapi.md` and `api-rest.md` exist with `paths:` front matter like `routes-convention.md`; every rule cites the ADR or doc it restates, and none contradicts one (checked by a reviewer pass, listed in the PR body).
- [ ] AC5 `protected-paths.md` lists every generated or secret path the repo has (`openapi.json`, `migrations/versions/**`, `.env.development`, `uv.lock`); a path this task finds missing is added.
- [ ] AC6 Every ADR that another ADR supersedes in part says so in its status line, with a link.
- [ ] AC7 No file under `docs/` or `.claude/` states something the code no longer does (the sweep lists each fix; each claim changed was checked against the code or a command run).

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| A stale claim is found whose correct form needs a decision | stop and list it under "needs a decision"; do not invent the decision | rule B4, F2 |
| The RUNBOOK's `docker run -p 5432:5432` collides with a Postgres already on the host (it did on this machine) | the RUNBOOK says how to pick another port and to set `DATABASE_URL` to match | AC1 |
| A rule file and an ADR disagree | the ADR wins; the rule is corrected, the disagreement noted in the PR | CLAUDE.md D2 |
| `CLAUDE.md`, `.claude/**` are ask-first paths | edits only after the hook's confirmation | protected-paths.md |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | `README.md` content | what it is, the two first-run paths in five lines each, links to RUNBOOK, ARCHITECTURE, docs/api, ADRs | no |
| A2 | Rule files restate, never decide | yes; a rule with no ADR behind it is left out and listed as a follow-up | confirm |
| A3 | Stale scope-doc rows (11.3 dropped, six services, `api/` paths, statuses) | not editable from the repo; the PR body lists them for the owner | yes |
| A4 | The two CI rows deferred in PR #38 | added here to the `CLAUDE.md` map | confirm |
