"""Revision 0002_seed_history as SQL, rendered offline. No database. Task: 5.1."""

import importlib
import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config import get_settings
from app.core.db import Base

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
REVISION_FILE = REPO_ROOT / "migrations" / "versions" / "0002_seed_history.py"


@pytest.fixture(autouse=True)
def offline_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://nobody@offline.invalid/none"
    )
    get_settings.cache_clear()


def render(*, upgrade: bool) -> str:
    output = io.StringIO()
    config = Config(str(ALEMBIC_INI), output_buffer=output)
    if upgrade:
        command.upgrade(config, "0001_init:0002_seed_history", sql=True)
    else:
        command.downgrade(config, "0002_seed_history:0001_init", sql=True)
    return output.getvalue()


def test_the_history_has_one_head_and_it_follows_the_initial_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))

    assert script.get_heads() == ["0002_seed_history"]
    revision = script.get_revision("0002_seed_history")
    assert revision is not None
    assert revision.down_revision == "0001_init"
    assert revision.module.__doc__ is not None
    assert "Rollback" in revision.module.__doc__


def test_the_revision_is_frozen_and_imports_nothing_from_the_app() -> None:
    source = REVISION_FILE.read_text()

    assert re.search(r"^\s*(from|import)\s+app\b", source, re.MULTILINE) is None


def test_upgrade_creates_only_the_seed_history_table_and_its_unique_index() -> None:
    sql = render(upgrade=True)

    assert re.findall(r'CREATE TABLE "([^"]+)"', sql) == ["SeedHistory"]
    assert re.findall(r'CREATE UNIQUE INDEX "([^"]+)"', sql) == ["SeedHistory_name_key"]
    assert "CREATE EXTENSION" not in sql


def test_the_columns_match_the_model() -> None:
    importlib.import_module("app.models")
    sql = render(upgrade=True)
    body = sql[sql.index('CREATE TABLE "SeedHistory"') :].split("\n);", 1)[0]
    created = [
        line.split()[0].strip('"')
        for line in (raw.strip() for raw in body.split("\n")[1:])
        if line and not line.startswith("CONSTRAINT")
    ]

    # Compared as sets: the model lists the mixin's `id` last, the revision first, as Prisma does.
    assert set(created) == {c.name for c in Base.metadata.tables["SeedHistory"].columns}
    assert created[0] == "id"


def test_downgrade_removes_only_the_seed_history_table() -> None:
    sql = render(upgrade=False)

    assert re.findall(r'DROP TABLE "([^"]+)"', sql) == ["SeedHistory"]
    assert "DROP TYPE" not in sql
