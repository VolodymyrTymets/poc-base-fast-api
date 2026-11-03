from app.cli import OPENAPI_PATH, contract_app
from app.core.openapi import is_current


def test_the_committed_openapi_json_matches_the_app() -> None:
    assert is_current(contract_app(), OPENAPI_PATH), (
        "openapi.json is stale: run `uv run python -m app.cli --export-openapi` and commit it"
    )
