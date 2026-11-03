"""Which seed items an environment gets. No database. Tasks: 5.1, 5.5."""

from typing import Literal

import pytest
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.seeds.items.init_roles import InitRoles
from app.seeds.registry import seed_items

type Env = Literal["local", "development", "test", "production"]


def names(app_env: Env) -> list[str]:
    # development and production refuse to boot without real-looking secrets (task 4.4).
    settings = Settings(
        app_env=app_env, jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY
    )
    return [item.name for item in seed_items(settings)]


def test_every_environment_gets_the_roles_first() -> None:
    assert names("production")[0] == InitRoles().name == "init.roles"


@pytest.mark.parametrize("app_env", ["local", "development", "test"])
def test_development_environments_get_the_roles_then_the_admin(app_env: Env) -> None:
    assert names(app_env) == ["init.roles", "init.admin"]


def test_production_gets_the_roles_only() -> None:
    assert names("production") == ["init.roles"]
