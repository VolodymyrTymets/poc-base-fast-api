import inspect
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.config import Settings
from app.core.db import Base
from app.main import create_app


def orm_routes(app: FastAPI) -> list[str]:
    """Routes whose response model is missing or is, or contains, an ORM class."""
    problems: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        model: Any = route.response_model
        if model is None:
            if route.status_code == 204:
                continue
            problems.append(f"{route.path}: no response model")
        elif _contains_orm(model):
            problems.append(f"{route.path}: ORM class in the response model")
    return problems


def _contains_orm(annotation: Any) -> bool:
    if inspect.isclass(annotation):
        if issubclass(annotation, Base):
            return True
        if issubclass(annotation, BaseModel):
            return any(
                _contains_orm(f.annotation) for f in annotation.model_fields.values()
            )
        return False
    return any(_contains_orm(arg) for arg in getattr(annotation, "__args__", ()))


def test_every_route_has_a_response_model_that_is_not_an_orm_class() -> None:
    assert orm_routes(create_app(Settings())) == []


def test_the_check_flags_a_route_with_no_response_model() -> None:
    app = create_app(Settings())

    @app.get("/untyped", response_model=None)
    async def untyped() -> dict[str, str]:
        return {}

    assert orm_routes(app) == ["/untyped: no response model"]


def test_the_check_flags_a_model_that_holds_an_orm_object() -> None:
    from pydantic import ConfigDict

    from app.models.account import Account

    class Leaky(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        account: Account

    app = create_app(Settings())

    @app.get("/leaky")
    async def leaky() -> Leaky:
        raise NotImplementedError

    assert orm_routes(app) == ["/leaky: ORM class in the response model"]


def test_a_204_route_may_have_no_response_model() -> None:
    app = create_app(Settings())

    @app.post("/gone", status_code=204)
    async def gone() -> None:
        return None

    assert orm_routes(app) == []
