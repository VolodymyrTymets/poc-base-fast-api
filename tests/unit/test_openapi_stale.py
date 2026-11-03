from app.core.openapi import is_current
from app.main import OPENAPI_PATH, contract_app


def test_the_committed_openapi_json_matches_the_app() -> None:
    assert is_current(contract_app(), OPENAPI_PATH), (
        "openapi.json is stale: run `uv run python -m app.main --export-openapi` and commit it"
    )
