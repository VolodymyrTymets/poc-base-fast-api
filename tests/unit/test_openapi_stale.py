from app.config import Settings
from app.core.openapi import is_current
from app.main import OPENAPI_PATH, create_app


def test_the_committed_openapi_json_matches_the_app() -> None:
    assert is_current(create_app(Settings()), OPENAPI_PATH), (
        "openapi.json is stale: run `uv run python -m app.main --export-openapi` and commit it"
    )
