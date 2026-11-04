"""A router never builds a service: it takes a provider from app/dependencies.py. Issue: I.9, ADR-0025."""

import ast
import inspect
from pathlib import Path

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.config import Settings
from app.main import create_app

ROUTERS = Path(__file__).parents[2] / "app" / "routers"


def service_names(tree: ast.AST) -> set[str]:
    """Every local name bound by an import from `app.services`, aliases included."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app.services"
        ):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name.startswith("app.services")
            )
    return names


def misuses(source: str) -> list[str]:
    """Names of services a router calls, or hands to `Depends` as a class."""
    tree = ast.parse(source)
    imported = service_names(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else ""
        )
        if callee in imported or callee.endswith("Service"):
            found.append(callee)
        if callee == "Depends":
            found.extend(
                arg.id
                for arg in node.args
                if isinstance(arg, ast.Name) and arg.id in imported
            )
    return found


def test_the_detector_finds_a_hand_built_service() -> None:
    assert misuses("x = AccountService(session)") == ["AccountService"]
    assert misuses("x = services.FileAssertService(s)") == ["FileAssertService"]
    assert misuses("x = Depends(get_account_service)") == []


def test_the_detector_finds_an_aliased_import_and_a_class_given_to_depends() -> None:
    aliased = "from app.services.account import AccountService as Svc\nx = Svc(s)\n"
    as_dependency = (
        "from app.services.account import AccountService\n"
        "def r(s=Depends(AccountService)): ...\n"
    )

    assert misuses(aliased) == ["Svc"]
    assert misuses(as_dependency) == ["AccountService"]


def test_no_router_constructs_a_service() -> None:
    offenders = {
        str(path.relative_to(ROUTERS)): found
        for path in sorted(ROUTERS.rglob("*.py"))
        if (found := misuses(path.read_text()))
    }

    assert offenders == {}


def dependency_calls(dependant: Dependant) -> list[object]:
    calls: list[object] = [dependant.call] if dependant.call else []
    for sub in dependant.dependencies:
        calls.extend(dependency_calls(sub))
    return calls


def test_no_route_depends_on_a_service_class_directly() -> None:
    routes = [r for r in create_app(Settings()).routes if isinstance(r, APIRoute)]
    classes = [
        call
        for route in routes
        for call in dependency_calls(route.dependant)
        if inspect.isclass(call) and call.__module__.startswith("app.services")
    ]

    assert classes == []
