"""Which seed items an environment gets. No database. Task: 5.1."""

from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.seeds import registry
from app.seeds.base import SeedItem
from app.seeds.items.init_roles import InitRoles
from app.seeds.registry import seed_items

type Env = Literal["local", "development", "test", "production"]


class Sample:
    name = "sample"

    async def needs_to_run(self, session: AsyncSession) -> bool:
        return True

    async def run(self, session: AsyncSession) -> None:
        return None


@pytest.fixture
def with_a_development_item(monkeypatch: pytest.MonkeyPatch) -> None:
    # Until task 5.5 the development list is empty, so the rule is tested with a stand-in.
    items: list[SeedItem] = [Sample()]
    monkeypatch.setattr(registry, "development_items", lambda: items)


def names(app_env: Env) -> list[str]:
    # development and production refuse to boot without real-looking secrets (task 4.4).
    settings = Settings(
        app_env=app_env, jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY
    )
    return [item.name for item in seed_items(settings)]


def test_every_environment_gets_the_roles_first() -> None:
    assert names("production")[0] == InitRoles().name == "init.roles"


@pytest.mark.parametrize("app_env", ["local", "development", "test"])
def test_development_items_run_in_the_development_environments(
    app_env: Env, with_a_development_item: None
) -> None:
    assert names(app_env) == ["init.roles", "sample"]


def test_production_gets_no_development_item(with_a_development_item: None) -> None:
    assert names("production") == ["init.roles"]
