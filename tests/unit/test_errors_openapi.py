from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import Settings
from app.main import create_app


class Payload(BaseModel):
    count: int


def spec_with_a_body_route() -> dict[str, Any]:
    app: FastAPI = create_app(Settings())

    # The real app has no route with a body yet, and FastAPI adds its default 422 only to a
    # route that has parameters or a body, so a test route is what makes this check mean something.
    @app.post("/api/v1/_payload")
    async def payload(body: Payload) -> None:
        return None

    return app.openapi()


def schema_ref(spec: dict[str, Any], status: str) -> str:
    response = spec["paths"]["/api/v1/_payload"]["post"]["responses"][status]
    ref: str = response["content"]["application/json"]["schema"]["$ref"]
    return ref


def test_validation_error_response_points_at_the_error_contract() -> None:
    spec = spec_with_a_body_route()

    assert schema_ref(spec, "422") == "#/components/schemas/ErrorResponse"


def test_unexpected_error_response_points_at_the_error_contract() -> None:
    spec = spec_with_a_body_route()

    assert schema_ref(spec, "500") == "#/components/schemas/ErrorResponse"


def test_fastapi_default_validation_schema_is_not_in_the_contract() -> None:
    spec = spec_with_a_body_route()

    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_every_route_of_the_real_app_documents_the_error_body() -> None:
    spec = create_app(Settings()).openapi()

    health = spec["paths"]["/api/v1/health"]["get"]["responses"]
    assert {
        status: health[status]["content"]["application/json"]["schema"]["$ref"]
        for status in ("422", "500")
    } == {
        "422": "#/components/schemas/ErrorResponse",
        "500": "#/components/schemas/ErrorResponse",
    }
