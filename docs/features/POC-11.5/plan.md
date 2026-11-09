# POC-11.5 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code. -->
Approved-by:

Pattern followed: `.claude/rules/routes-convention.md` for the rule-file shape (front matter `description` and `paths`, numbered rules, "Decided in ADR-n, the ADR wins"), the existing RUNBOOK sections for tone, ADR-0011 for the layer rules the new files point to. Docs only: no code, test or workflow file changes, so no new ADR (rule D1 is not triggered); `openapi.json` and `uv.lock` untouched.

## Contract changes
- boundary, config, dependencies, generated output: none.
- ask-first paths touched: `CLAUDE.md`, `.claude/rules/**` (hook confirmation when it asks, human reviewer on the PR).

## Requirements (branch `docs/POC-11.5-docs-and-rules`, one draft PR, one commit each)

### R1 — follow the RUNBOOK from a clean clone (M, first: it finds the real gaps)
- `git clone` the repo into a scratch directory; follow "First run" with uv (a throwaway Postgres container on a free port, the matching `DATABASE_URL`), then "Docker Compose" in a second clone. Call health, the OTP request and verify, and read the worker log.
- Record every step that failed, was missing or was ambiguous (the host-port collision already seen is one). Fix those lines in `docs/RUNBOOK.md` now; the later requirements build on the corrected text.
- files: `docs/RUNBOOK.md`. executed how: the commands in the clone, output pasted in the PR. Cleanup: the clones and containers are removed with plain `docker rm` and `rm` of the scratch directories I created (their names listed), no volume removal.

### R2 — stale-doc sweep (M)
- For each of `docs/ARCHITECTURE.md`, `docs/BUSINESS_MODEL.md`, `docs/DOMAIN_GLOSSARY.md`, `docs/RUNBOOK.md`, `docs/AGENT_TOOLING.md`, `docs/api/*.md`, `.claude/rules/*.md`: grep every claim that names a file, command, setting, route or task status and check it against the code or by running it. Known stale: BUSINESS_MODEL "only the uv init skeleton exists" and "49 tasks, about 175 h"; ARCHITECTURE "Status: skeleton"; the Planned section, which must list only what is still unbuilt (the Redis read cache, package 8's file routes).
- A claim whose fix needs a decision is listed in the PR body, not guessed (rule B4).
- files: the docs above. executed how: a table in the PR body, claim, where, how checked, fix.

### R3 — `README.md` (S)
- files: `README.md` (A1). The Dockerfile copies it and `pyproject.toml` may name it as the readme, so `uv build` and `docker build --target base .` are re-run.
- executed how: every command in it run once; `uv build`; the docker build.

### R4 — rule files (M)
- `.claude/rules/backend-fastapi.md` (`paths: app/**`): async only, no blocking call in a coroutine (Argon2 through the thread seam, ADR-0028), the session and transaction rules (ADR-0021, 0025, 0027), models and naming (ADR-0004, 0014, 0016), settings read once (`get_settings`), logging redaction (P4), soft deletes only (P6), jobs through `QueueClient` (ADR-0005, 0024). Each rule cites its ADR or rule ID.
- `.claude/rules/api-rest.md` (`paths: app/routers/**`, `app/schemas/**`, `app/core/errors.py`, `openapi.json`, `docs/api/**`): `/api/v1`, camelCase fields, one error body and its codes (ERRORS.md, ADR-0003), 401 versus 403 versus 404 rules (ADR-0022, P7), `StrictModel` and `extra="forbid"` (task 4.3), response models never ORM objects, the generated `openapi.json` and its stale-spec test, multipart files (ADR-0009), no secrets or tokens in responses (P4).
- Rules restate decided text only (A2). Anything with no ADR behind it is not written; it goes in the PR body as a follow-up.
- `protected-paths.md`: check against the tree and add what is missing (AC5).
- executed how: a reviewer pass (`rln-agent:code-reviewer`) comparing each rule to its cited ADR; `uv run pytest tests/unit` stays green because some unit tests read these files.

### R5 — `CLAUDE.md` and ADR status lines (S)
- `CLAUDE.md`: add command-map rows for `docker compose up -d --build` / `down`, `uv run pytest -m "not e2e"` (what CI's test job runs), `uv sync --locked`, `./set-ports.sh <BASE>` and `./move-env.sh <dir>` (A4); update the `P2` ADR range; keep under 200 lines; add the two new rule files to "Where things live".
- ADR status lines (AC6): audit every `Supersedes:` line against the superseded ADR's status; add the missing back-references (for example a note on ADR-0021 that ADR-0025 and ADR-0027 extend it, if their text says "extends"). Status lines only, no body edits.
- executed how: `wc -l CLAUDE.md`; a one-off script (not committed) that checks every `Supersedes` target mentions the superseder.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest -m "not db and not redis"`, `uv run python -m app.cli --export-openapi --check`, `uv build`; CI's three jobs green on the PR.

## Docs to update in this PR
This task is the docs; the spec's ACs are ticked at the end. DOMAIN_GLOSSARY: only if the sweep finds a missing term (none expected).

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| a rule file states something an ADR does not | a rule the agent obeys that nobody decided | R4 reviewer pass against the cited ADRs |
| a unit test pins the text of a rule or doc file | a red test after an edit | run `tests/unit` after each edit |
| the clean-clone run needs Docker ports already in use on this machine | R1 blocked | pick free ports (5432 is taken by a local Postgres here) |
| the sweep grows past one PR | C1, B4 | cap at the files listed; list the rest as a follow-up |

## Assumptions
- A1-A4 of the spec; whoever writes `Approved-by:` also confirms A2 (rules restate only) and A3 (scope doc statuses left for the owner).

## Estimate
R1 M · R2 M · R3 S · R4 M · R5 S
