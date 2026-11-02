# POC-3.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving also approves Q2 (flat layout kept) of spec.md. Note: `.claude/**` is "ask first" in protected-paths.md,
     so each write under it will ask for confirmation.
     Approved-by: <name> · <date> -->
Approved-by: volodymyr - 2026-11-02

Pattern followed: the rule files `.claude/rules/project-structure.md` and `python-tooling.md` (repo-specific, cite ADRs and paths), and the
existing suite as the style source: `tests/unit/test_fake_queue.py` (unit), `tests/e2e/test_http_client.py` (e2e), `tests/conftest.py` (fixtures).
There is no skill precedent in this repo (no `.claude/skills/`); the plugin skill `write-tests` is language-neutral. The skill layout follows the
standard `SKILL.md` with `name` and `description` frontmatter. Skills are new here, so I checked nothing against an ADR: none covers it, none is needed for a docs-only skill.

## Contract changes
- boundary: none. data: none. generated output: none. `app/`, `tests/` code, `pyproject.toml`, `uv.lock`: untouched.
- documentation contract: the rule file and the skill become the stated test conventions; later tasks (4.x to 9.x) cite them.

## Requirements (ordered; branch `feat/POC-3.3-test-conventions`, one draft PR, one commit each)

### R1 — Rewrite `testing-python.md` (M)
- files: `.claude/rules/testing-python.md` (change: full rewrite; frontmatter `paths` kept, `description` rewritten too: it still names hardware, GUI and import-time side effects).
- content: levels (`tests/unit` vs `tests/e2e`, decided by "needs Docker, database or the app over HTTP?"); flat `test_<area>.py`; async tests are plain `async def` (`asyncio_mode = "auto"`, no marker); the fixture table from `tests/conftest.py` (`database_url`, `template_database`, `module_database_url`, `db_engine`, `db_session`, `asgi_app`, `client`, `queue`, `frozen_clock`) with the when-to-use line each; boundary mocks only (clock via `frozen_clock`, jobs via `queue`, network and SMS/email by a hand-written fake, never the database, P8); `frozen_clock` caveat (process clock only, `CURRENT_TIMESTAMP` is the server's); no sleeps; parametrize with `ids`; `--strict-markers` is on and no markers are registered, so a new marker is registered in `pyproject.toml` first (ask-first file); no skip/xfail without `WHY:` (B3); coverage is a diagnostic; bug fix = failing test first. Dropped: hardware, GUI, serial, import-time singletons, `tests/test_<module>.py`.
- layer: agent config (docs).
- test: none for prose; the check is mechanical: grep that every fixture and path named exists (AC5), and that the file has no rule contradicting `testing.md`.
- executed how: `grep -o` of each backticked fixture name against `tests/conftest.py`; `ls` of each named path; output pasted.
- risk: rules drift from the fixtures. Cheapest guard: rules name fixtures and defer detail to their docstrings.

### R2 — Create the `test-conventions` skill (M)
- files: `.claude/skills/test-conventions/SKILL.md` (new). Frontmatter: `name: test-conventions`, `description:` when to use (writing or changing a test in this repo, choosing unit vs e2e, picking a fixture).
- content: a decision table (what you test, level, fixtures); the unit example (a pure function, `parametrize` with `ids`, `pytest.raises(match=)`, `frozen_clock` for an expiry rule, using only real repo symbols such as `app.core.logging` redaction or `app.core.db.utc_now`); the e2e example (`client` plus a test-local route added to `asgi_app`, as `tests/e2e/test_http_auth_helper.py` and `tests/e2e/test_frozen_clock.py` do, and a `queue` assertion: the app does not use the queue until task 6.1, so the test route calls `queue.enqueue` itself and the skill says so); a "do not" list pointing at rules B3, P8; a pointer to `testing-python.md` rather than repeating it.
- layer: agent config (docs).
- test: AC4. Copy each example verbatim into `tests/unit/test_zz_skill_example.py` and `tests/e2e/test_zz_skill_example.py`, run them, run `ruff` and `mypy` on them, then delete both copies (`git status` clean of them). Examples must not need a new fixture.
- executed how: `uv run pytest tests/unit/test_zz_skill_example.py tests/e2e/test_zz_skill_example.py -v` (Docker running), plus `uv run ruff check`, `ruff format --check`, `mypy`; output pasted. The e2e example needs the module database, so it uses the same Docker path as the rest of e2e.
- risk: an example looks right but is wrong at run time (the whole point of AC4). Cheapest experiment: run it before writing the surrounding prose.

### R3 — Remove the "set by task 3.3" placeholders, add pointers (S)
- files: `.claude/rules/project-structure.md` (change: the `tests/` line in the tree, and rule 8 which says "task 3.3 sets it" and mentions `tests/test_<module>.py`: both get the decided layout, flat `test_<area>.py` under `tests/unit` and `tests/e2e`, and a pointer to `testing-python.md`), `docs/ARCHITECTURE.md` (change: the `tests/` row says the layout is set, points to the rule and the skill), `docs/RUNBOOK.md` (change: one line in "HTTP tests" pointing to the skill), `docs/features/POC-3.3/spec.md` (ACs ticked).
- layer: docs.
- test: AC5: `grep -rn "task 3.3" .claude docs/ARCHITECTURE.md docs/RUNBOOK.md` returns nothing (it does not search `docs/features/`).
- executed how: the grep, then the full gate: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e`, outputs pasted.
- risk: none.

## Docs to update in this PR
- [ ] docs/features/POC-3.3/spec.md (ACs checked), docs/ARCHITECTURE.md (tests row), docs/RUNBOOK.md (pointer) (rule E1)
- [ ] DOMAIN_GLOSSARY: no new term. ADR: none (no new pattern in code; the rule file records an existing convention).
- Scope doc row 3.3 status is the human's (rule E2: noted in the PR body).

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A skill example fails when run | AC4 | R2: run examples before writing prose |
| `.claude/**` writes prompt for confirmation each time | slows R1 to R3 | expected (protected-paths.md "Ask first"); batch edits per file |
| Plugin `/setup` or update overwrites the rewritten rule | lost rewrite | PR body notes it; repo-specific header in the file |

## Assumptions
- Files are staged by path; the untracked scope doc and `.serena/` stay out of the PR (A4, C1).
- Spec Q1 to Q3 hold. Docker is running for the e2e runs. Python is the `uv` interpreter (3.14, T2).
- Work starts from `main` on a new branch `feat/POC-3.3-test-conventions` (the session briefing's `feat/POC-3.2-...` branch is merged; `git branch` shows `main`).
- Estimate: R1 M, R2 M, R3 S. Scope-doc estimate is 2 h.
