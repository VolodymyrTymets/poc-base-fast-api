import inspect
from collections.abc import Callable
from typing import Any, NamedTuple

from fastapi import FastAPI, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.config import Settings
from app.core.db import Base
from app.main import create_app

# Routes that answer with bytes, not JSON, so they have no response model (task 8.3, ADR-0009). The body is one column
# read by the service, never an ORM object. Add a path here only with that reason.
BYTE_ROUTES = {"/api/v1/files/{id}/content"}


class RouteInfo(NamedTuple):
    path: str
    response_model: Any
    status_code: int | None
    endpoint: Callable[..., Any] | None


def api_routes(app: FastAPI) -> list[RouteInfo]:
    """Every API route of the app, with the prefixes of the routers included into it.

    FastAPI keeps an included router as one opaque entry in `app.routes` (an `_IncludedRouter`), so looking only for `APIRoute`
    there finds the routes added straight to the app and none of the feature routes. That entry lists its routes in
    `effective_route_contexts()`.
    """
    found: list[RouteInfo] = []
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            found += [
                RouteInfo(
                    c.path,
                    c.response_model,
                    getattr(c.original_route, "status_code", None),
                    c.endpoint,
                )
                for c in contexts()
            ]
        elif isinstance(route, APIRoute):
            found.append(
                RouteInfo(
                    route.path, route.response_model, route.status_code, route.endpoint
                )
            )
    return found


def orm_routes(app: FastAPI) -> list[str]:
    """Routes whose response model is missing or is, or contains, an ORM class.

    A 204 route may have none. A route that returns bytes is named in `BYTE_ROUTES` with its reason.
    """
    problems: list[str] = []
    for route in api_routes(app):
        model = route.response_model
        if model is None:
            if route.status_code == 204 or route.path in BYTE_ROUTES:
                continue
            problems.append(f"{route.path}: no response model")
        elif _contains_orm(model):
            problems.append(f"{route.path}: ORM class in the response model")
    return problems


def _contains_orm(annotation: Any, seen: frozenset[type] = frozenset()) -> bool:
    if inspect.isclass(annotation):
        if annotation in seen:
            return False
        seen = seen | {annotation}
        if issubclass(annotation, Base):
            return True
        if issubclass(annotation, BaseModel):
            return any(
                _contains_orm(f.annotation, seen)
                for f in annotation.model_fields.values()
            )
        return False
    return any(_contains_orm(arg, seen) for arg in getattr(annotation, "__args__", ()))


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


def test_the_check_sees_the_routes_of_the_included_routers() -> None:
    paths = {route.path for route in api_routes(create_app(Settings()))}

    assert {"/api/v1/health", "/api/v1/files", "/api/v1/files/{id}/content"} <= paths


def test_a_route_added_through_an_included_router_is_flagged_when_it_has_no_model() -> (
    None
):
    app = create_app(Settings())
    # A real router included the way create_app includes the feature routers, not a route added straight to the app.
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/bare", response_model=None)
    async def bare() -> dict[str, str]:
        return {}

    app.include_router(router, prefix="/api/v1")

    assert orm_routes(app) == ["/api/v1/bare: no response model"]


def test_every_byte_route_exists_and_returns_a_response() -> None:
    returns = {
        route.path: route.endpoint.__annotations__.get("return")
        for route in api_routes(create_app(Settings()))
        if route.endpoint is not None and route.path in BYTE_ROUTES
    }

    assert returns == dict.fromkeys(BYTE_ROUTES, Response)
