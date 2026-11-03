import pkgutil
from types import ModuleType

from fastapi import APIRouter

import app.routers
from app.config import Settings
from app.main import ROUTERS, create_app


def router_modules() -> list[ModuleType]:
    return [
        __import__(f"app.routers.{info.name}", fromlist=["router"])
        for info in pkgutil.iter_modules(app.routers.__path__)
    ]


def test_every_router_module_has_a_router_tagged_with_its_name() -> None:
    modules = router_modules()

    assert modules
    for module in modules:
        name = module.__name__.rsplit(".", 1)[1]
        router = module.router
        assert isinstance(router, APIRouter), name
        assert router.tags == [name], name


def test_the_app_lists_one_tag_per_router_module() -> None:
    expected = sorted(m.__name__.rsplit(".", 1)[1] for m in router_modules())

    listed = sorted(tag["name"] for tag in create_app(Settings()).openapi()["tags"])

    assert listed == expected


def test_create_app_includes_every_router_module() -> None:
    assert sorted(m.__name__ for m in ROUTERS) == sorted(
        m.__name__ for m in router_modules()
    )
