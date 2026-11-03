"""Rendering and checking of the exported OpenAPI contract (ADR-0003). Task: 4.1.

Pure helpers: the command that builds the app and calls them lives in `app/cli.py`, because
`core` imports no layer.
"""

import json
from pathlib import Path

from fastapi import FastAPI


def render(app: FastAPI) -> str:
    # Sorted keys and a trailing newline keep the file stable between runs and in diffs.
    return (
        json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def is_current(app: FastAPI, path: Path) -> bool:
    return path.is_file() and path.read_text(encoding="utf-8") == render(app)
