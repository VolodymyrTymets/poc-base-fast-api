from pathlib import Path

from app.core.openapi import is_current, render
from app.main import ContractSettings, contract_app, create_app, export_openapi


def test_render_is_deterministic_and_ends_with_a_newline() -> None:
    first = render(contract_app())
    second = render(contract_app())

    assert first == second
    assert first.endswith("}\n")


def test_the_spec_does_not_depend_on_settings() -> None:
    plain = render(contract_app())
    other = render(
        create_app(
            ContractSettings(
                app_env="production",
                sentry_dsn=None,
                cors_origins=["http://x.test"],
                log_level="DEBUG",
            )
        )
    )

    assert plain == other


def test_export_writes_what_render_returns(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    status = export_openapi(target)

    assert status == 0
    assert target.read_text(encoding="utf-8") == render(contract_app())


def test_check_passes_on_a_current_file_and_fails_on_a_changed_one(
    tmp_path: Path,
) -> None:
    target = tmp_path / "openapi.json"
    export_openapi(target)
    assert export_openapi(target, check=True) == 0

    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")

    assert export_openapi(target, check=True) == 1


def test_check_fails_when_the_file_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "openapi.json"

    assert is_current(contract_app(), missing) is False
    assert export_openapi(missing, check=True) == 1
