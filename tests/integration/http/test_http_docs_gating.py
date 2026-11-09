"""The contract pages are served only for local and development. Task: POC-11.6 (ADR-0033). No database: the lifespan is not run."""

from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.openapi import render
from app.main import create_app

PAGES = ["/docs", "/redoc", "/openapi.json"]
AppEnv = Literal["local", "development", "test", "production"]


def app_for_env(app_env: AppEnv) -> FastAPI:
    # development and production refuse to boot without two different long secrets (task 4.4).
    return create_app(
        Settings(
            app_env=app_env,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )


@pytest.mark.parametrize("app_env", ["production", "test"])
@pytest.mark.parametrize("path", PAGES)
def test_the_contract_pages_answer_404_outside_local_and_development(
    app_env: AppEnv, path: str
) -> None:
    # Arrange
    client = TestClient(app_for_env(app_env))

    # Act
    response = client.get(path)

    # Assert
    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "NOT_FOUND",
    )


@pytest.mark.parametrize("app_env", ["local", "development"])
@pytest.mark.parametrize("path", PAGES)
def test_the_contract_pages_answer_200_in_local_and_development(
    app_env: AppEnv, path: str
) -> None:
    # Arrange
    client = TestClient(app_for_env(app_env))

    # Act
    response = client.get(path)

    # Assert
    assert response.status_code == 200


def test_the_served_contract_lists_the_health_route() -> None:
    # Arrange
    client = TestClient(app_for_env("development"))

    # Act
    response = client.get("/openapi.json")

    # Assert
    assert "/api/v1/health" in response.json()["paths"]


@pytest.mark.parametrize("app_env", ["production", "test", "development"])
def test_the_exported_contract_is_the_same_in_every_environment(
    app_env: AppEnv,
) -> None:
    # Arrange
    local = render(app_for_env("local"))

    # Act
    other = render(app_for_env(app_env))

    # Assert
    assert other == local
