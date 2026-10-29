---
description: Python tooling rules - one dependency manager, a project venv, pinned versions, ruff, dependency additions, generated artefacts.
paths:
  - "requirements*.txt"
  - "**/requirements*.txt"
  - "requirements*.in"
  - "pyproject.toml"
  - "**/pyproject.toml"
  - "uv.lock"
  - "poetry.lock"
  - "Pipfile"
  - "Pipfile.lock"
  - ".python-version"
  - "ruff.toml"
  - ".ruff.toml"
  - "pytest.ini"
  - "tox.ini"
  - "noxfile.py"
---

# Python tooling rules

Core rules T1–T4 already cover the command map, the pinned runtime, the single dependency manager and pipeline files. These add what is specific to Python.

1. The dependency manager is the one the repo declares: `uv.lock` or `[tool.uv]` → uv, `poetry.lock` → poetry, `Pipfile` → pipenv, otherwise a pinned `requirements*.txt` → pip. Never mix managers, never delete or hand-edit a lockfile or requirements file by guessing — change the declaration and let the tool regenerate (hook `py-tooling-1`, `py-tooling-3`).
2. **Install only into the project venv.** A bare `pip install` goes into whichever Python is first on `PATH`. Use `.venv/bin/pip …`, activate first, or use `uv`/`poetry`. Never `--break-system-packages`, never `sudo pip` (hook `py-tooling-2`).
3. The interpreter is the one the version file pins (`.python-version`, `requires-python`). If the local interpreter differs, stop and report (rule T2) — do not work around it with a syntax or library that only exists on another version.
4. Pin every dependency to an exact version (`==`) or to the lockfile. A bump of a pinned library is its own PR, because pins often exist for a reason that is not written down (rule C2, C1).
5. A new dependency is a decision: justify need, size, licence and maintenance in the PR, and prefer the standard library or what the repo already has. Development-only tools go in the dev group or `requirements-dev.txt`, never in the runtime list.
6. Lint and format with **ruff** when the repo configures it, and only with the repo's own config. Widening the rule set, or running `ruff format` on a file the repo never formatted, is a separate PR (rule C1). The formatter hook runs only when the repo declares a `[format]` section.
7. Never silence a check to make it pass: no `# noqa` or `# type: ignore` without a human-approved `# WHY:` (rule B3).
8. Generated output (protobuf stubs, API clients, compiled UI files) is never hand-edited; fix the source and re-run the generator from the command map (rule C3).
9. Never commit `.venv/`, `__pycache__/`, `*.pyc`, `*.egg-info/` or build output; they are protected paths.
