# POC-1.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving confirms the assumed answers in spec.md (edit them first to change one). Format:
     Approved-by: volodymyr · <date> -->
Approved-by:  volodymyr · 2026-10-2

Pattern followed: the project structure in the scope doc's task 1.3 (rev 114), which is the authority for this task and which
the other rows' file paths already use; dependency direction after ADR-0003 (transport at the edge, services below it). Build
settings from the uv documentation (checked with Context7): `[tool.uv.build-backend]` with `module-name = "app"` and
`module-root = ""` puts the module at the repo root. No Python precedent exists in this repo yet. Layer: package structure.

## Contract changes
- boundary: none. data: none. generated output: none.
- the importable name changes from `poc_base_fast_api` to `app`; the console script `poc-base-fast-api` keeps its name.

## Requirements (ordered, each independently verifiable, one commit each)

Branch `feat/POC-1.3-project-structure`, one draft PR (rule A4). No dependency (rule C2). No test runner exists until 1.4
(ADR-0007), so each requirement is proven by running a command and pasting its output; everything runs through `uv run`.
**Order of work:** R2 first, then R1, R3, R4, R5. R2 carries the riskiest unknown (whether `uv_build` accepts a root-level module), so
the ADR in R1 is written and accepted only after R2's wheel listing passes.

### R1 — ADR-0011: root `app/` package, layered structure (S)
- files: `docs/decisions/ADR-0011-project-structure.md` (new), `docs/decisions/ADR-0010-repo-layout-and-configuration.md` (change: Status line gains "package location superseded by ADR-0011").
- content: supersedes ADR-0010's package location only (API-only, `APP_ENV` and the env names stay); the layers, `core/`, `workers/`, `seeds/` and what each holds; **the import direction** (routers use services, schemas and dependencies; services use models, schemas and core; models import only from core; `core` imports from no layer; `workers` and `seeds` use services and models), which `project-structure.md` cites rather than redefines; why not `src/poc_base_fast_api/` with feature packages; consequences (generic top-level name; unused layer files); revisit when a second deployable appears.
- test: the POC-1.1 ADR checks on the new file (date, status `accepted`, deciders `volodymyr`, ticket `POC-1.3`, five sections, alternatives table, `Supersedes`) each print their expected count; `grep -c "ADR-0011" docs/decisions/ADR-0010-*.md` prints 1.
- executed how: run the checks in bash and paste the output.

### R2 — Move the package to `app/` (S)
- files: `app/__init__.py` (moved from `src/poc_base_fast_api/__init__.py`, content unchanged), `pyproject.toml` (change: add `[tool.uv.build-backend]` with `module-name = "app"` and `module-root = ""`; `[project.scripts]` becomes `poc-base-fast-api = "app:main"`), `src/` removed with `git mv`.
- layer: build and packaging. `pyproject.toml` is an ask-first path; the plan is the approval.
- test: `uv sync` ok; `uv build` ok; `unzip -l dist/poc_base_fast_api-0.1.0-py3-none-any.whl | grep -c "app/__init__.py"` prints `1` and `grep -c "poc_base_fast_api/"` prints `0`; `uv run python -I -c "import app; print(app.__file__)"` prints a path under the repo root.
- executed how: `uv run poc-base-fast-api` prints `Hello from poc-base-fast-api!`.
- risk: `uv_build` mis-locating the module; the wheel listing proves it.

### R3 — The skeleton (M)
- files (all new): `app/main.py`, `app/config.py`, `app/dependencies.py`; `app/{routers,schemas,models,services}/__init__.py` and, in each of those four, `account.py`, `account_profile.py`, `account_role.py`, `auth.py`, `files.py`, `notifier.py`; `app/core/__init__.py`, `app/workers/__init__.py`, `app/seeds/__init__.py`; `tests/.gitkeep`. That is 34 new modules plus `app/__init__.py`.
- each docstring is one line: what the module will hold, and the tasks that fill it, taken from the scope-doc rows (for example `app/models/account.py`: SQLAlchemy tables `Account`, `AccountIdentity`, `AccountOnRole` (task 2.2); `app/core/__init__.py`: cross-cutting code, one module per concern (1.5, 1.6, 2.1, 4.2 to 4.4, 9.1, 9.3); `app/workers/__init__.py`: arq worker and jobs (6.1, 6.2); `app/seeds/__init__.py`: seed runner and items (5.1, 5.5)). A module with no task citing it says so ("no task cites this file yet"). No code, no imports.
- layer: structure only. No `.env` (secret, gitignored), no `.env.example` (1.5).
- test 1, import: `uv run python -I -c "import pkgutil, importlib, app; n=[importlib.import_module(m.name) for m in pkgutil.walk_packages(app.__path__, 'app.')]; print(len(n)+1, 'imported')"` prints `35 imported`.
- test 2, docstring-only (AC3): `uv run python -I -c "..."` with `ast` asserts, for the 34 new files, one statement that is a string; prints `34 docstring-only`, exits 0.
- test 3, tree (AC2): `find app tests -not -name '*.pyc' -not -name __pycache__ -type f | sort | wc -l` prints `36` (35 `.py` plus `.gitkeep`), and the sorted list is pasted next to the expected one.
- test 4, `src/` gone: `git mv` leaves the ignored `src/poc_base_fast_api/__pycache__/` on disk, so `test ! -e src` fails until it is removed. Removing it is `rm -rf src` (rule C4): the implementer asks volodymyr for explicit confirmation in that message, then `test ! -e src && echo "src gone"` prints `src gone`.
- executed how: the four commands, plus `uv run poc-base-fast-api` again.

### R4 — The rule `project-structure.md` (S)
- files: `.claude/rules/project-structure.md` (new; ask-first path, the plan is the approval).
- content: front matter `description` and `paths: ["app/**", "tests/**"]`. Body: the tree; what each layer and `core/`, `workers/`, `seeds/` hold; the six modules and that a new feature adds `<module>.py` to the layers it needs; the import direction (routers use services, schemas and dependencies; services use models, schemas and core; models import only from core; `core` imports from no layer; `workers` and `seeds` use services and models; `main.py` only wires; no business logic in routers; no framework objects in services, ADR-0003); tests mirror `app/` under `tests/`; any new top-level module or layer needs an ADR (rule D1).
- test: `head -6 .claude/rules/project-structure.md` shows the front matter with both globs; one `grep -c` each for the four required parts (the layers, the import direction, where a new feature goes, "needs an ADR") prints at least 1; `wc -l` stays under 70.
- executed how: the checks above, output pasted. Whether Claude Code loads the rule is only observable on the next edit under `app/`, so it is listed under "Not verified" in the PR.

### R5 — Update ARCHITECTURE.md (S)
- files: `docs/ARCHITECTURE.md`, with these changes:
  - the status line and the `## Decided (ADR-0003 to ADR-0010, ...)` heading both say "ADR-0003 to ADR-0010" and become "ADR-0003 to ADR-0011";
  - the "Repo layout" table lists `app/` and its layers instead of `src/poc_base_fast_api/`, and the sentence "single package in a `src` layout at the repo root" is replaced;
  - the "Decided" bullet for the layout cites ADR-0011;
  - the "Planned" bullet "Packages by feature: ..." is removed (the layout now exists and is described in the table);
  - the landmine "ADR-0010 puts the package at the repo root" is reworded: ADR-0011 puts it in `app/`, and the scope doc's remaining first-half text of row 1.3 is stale.
- test: `grep -n -E "src. layout|Packages by feature|ADR-0003 to ADR-0010|src/poc_base_fast_api" docs/ARCHITECTURE.md` prints nothing; after `uv build`, `unzip -l dist/poc_base_fast_api-0.1.0-py3-none-any.whl | grep -c -E " app/.*\.py$"` prints `35` and `grep -c -E " (tests|poc_base_fast_api)/"` prints `0`; `git diff --name-only main` lists only paths under `app/`, `tests/`, `.claude/rules/`, `docs/` and `pyproject.toml`, with `src/` deleted.
- executed how: run the greps and `uv sync && uv build && uv run poc-base-fast-api`, and paste the output. Then prove AC1 from scratch, after committing: `git clone . <scratchpad>/fresh`, then in it `uv sync && uv run python -I -c "import app; print(app.__file__)"` prints a path under the clone (the clone stays in the scratchpad, not deleted, rule C4).
- not edited here, listed in the PR body for the human: the scope doc (my dated note "read `app/` as `src/poc_base_fast_api/`" is now false; the first half of row 1.3 still says copy `web/`, compose, ports and work in `api/`), `CLAUDE.md` rule P2 (its `app/` wording; ask-first path) and ADR-0010 line 14 (covered by the Status note).

## Docs to update in this PR
- [ ] docs/features/POC-1.3/spec.md (acceptance criteria ticked)
- [ ] docs/ARCHITECTURE.md — R5; docs/decisions/ADR-0011 and the ADR-0010 note — R1
- [ ] docs/DOMAIN_GLOSSARY.md — none expected

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| `uv_build` ignores `module-root = ""` or includes `tests/` | wrong wheel | R2 wheel listing, then the count of 35 in R5 |
| Layer files that no task will use (for example `routers/notifier.py`) | dead modules | their docstring says "no task cites this file yet"; they can be deleted in a later PR |
| My dated note in the scope doc is now wrong | misleading note | listed in the PR body as the first line to correct |
| Generic top-level name `app` | collision if installed beside another `app` | accepted for a single-application image; stated in ADR-0011 |

## Assumptions
- Spec questions 1 to 3 hold; the `Approved-by:` line confirms them.
- Estimates: R1 S, R2 S, R3 M (34 small files), R4 S, R5 S (the scope doc says 4 h for the whole task).
- PR #3 is merged; ticket `POC-1.3`; the human reviewer is volodymyr.
