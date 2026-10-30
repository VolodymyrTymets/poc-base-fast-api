import importlib


def test_app_package_imports() -> None:
    assert "ADR-0011" in (importlib.import_module("app").__doc__ or "")
