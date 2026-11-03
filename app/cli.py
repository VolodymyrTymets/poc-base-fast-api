"""Command-line entry points that need the whole app: today `python -m app.cli --export-openapi`. Task: 4.1, ADR-0020."""

import argparse
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic_settings import SettingsConfigDict

from app.config import Settings
from app.core.openapi import is_current, render
from app.main import create_app

# The committed contract at the repo root (ADR-0003); generated, never hand-edited.
OPENAPI_PATH = Path(__file__).resolve().parent.parent / "openapi.json"
EXPORT_COMMAND = "uv run python -m app.cli --export-openapi"


class ContractSettings(Settings):
    """Settings that ignore `.env`; init arguments still win over the environment."""

    model_config = SettingsConfigDict(env_file=None)


def contract_app() -> FastAPI:
    """The app the contract is taken from. Fixed settings: the file must not depend on a developer's
    `.env` or environment, and a command that only writes a file must not start Sentry."""
    return create_app(
        ContractSettings(app_env="local", sentry_dsn=None, database_url=None)
    )


def export_openapi(path: Path = OPENAPI_PATH, *, check: bool = False) -> int:
    """Write the OpenAPI contract to `path`, or with `check` only compare it. Returns the exit status."""
    app = contract_app()
    if check:
        if is_current(app, path):
            return 0
        sys.stderr.write(f"{path.name} is stale: run `{EXPORT_COMMAND}`\n")
        return 1
    path.write_text(render(app), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="Project commands."
    )
    parser.add_argument("--export-openapi", action="store_true", required=True)
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    parser.add_argument("--path", type=Path, default=OPENAPI_PATH)
    options = parser.parse_args(argv)
    return export_openapi(options.path, check=options.check)


if __name__ == "__main__":
    sys.exit(main())
