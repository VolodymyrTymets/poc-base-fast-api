"""A router never builds a service: it takes a provider from app/dependencies.py. Issue: I.9, ADR-0025."""

import ast
from pathlib import Path

ROUTERS = Path(__file__).parents[2] / "app" / "routers"


def constructed_services(source: str) -> list[str]:
    calls = (node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call))
    names = (
        call.func.id
        if isinstance(call.func, ast.Name)
        else call.func.attr
        if isinstance(call.func, ast.Attribute)
        else ""
        for call in calls
    )
    return [name for name in names if name.endswith("Service")]


def test_the_detector_finds_a_hand_built_service() -> None:
    assert constructed_services("x = AccountService(session)") == ["AccountService"]
    assert constructed_services("x = services.FileAssertService(s)") == [
        "FileAssertService"
    ]
    assert constructed_services("x = Depends(get_account_service)") == []


def test_no_router_constructs_a_service() -> None:
    offenders = {
        path.name: found
        for path in sorted(ROUTERS.glob("*.py"))
        if (found := constructed_services(path.read_text()))
    }

    assert offenders == {}
