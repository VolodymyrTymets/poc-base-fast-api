"""The Alembic environment (POC-2.4): where it finds its script directory and its database URL. No database."""

import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def make_config(output: io.StringIO | None = None) -> Config:
    # An absolute path: the autouse fixture in conftest.py runs every test from an empty directory.
    return Config(str(ALEMBIC_INI), output_buffer=output)


def test_the_ini_holds_no_database_url() -> None:
    assert make_config().get_main_option("sqlalchemy.url") is None
    assert "postgresql" not in ALEMBIC_INI.read_text()


def test_the_script_directory_is_found_from_any_working_directory() -> None:
    script = ScriptDirectory.from_config(make_config())

    assert Path(script.dir) == REPO_ROOT / "migrations"


@pytest.mark.parametrize("offline", [True, False], ids=["offline", "online"])
def test_a_missing_database_url_fails_with_a_message_naming_it(offline: bool) -> None:
    with pytest.raises(CommandError, match="DATABASE_URL"):
        command.upgrade(make_config(), "head", sql=offline)


def test_offline_mode_renders_from_settings_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `.invalid` never resolves, so a connection attempt would fail the test.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://nobody@offline.invalid/none"
    )
    get_settings.cache_clear()

    command.upgrade(make_config(io.StringIO()), "head", sql=True)
