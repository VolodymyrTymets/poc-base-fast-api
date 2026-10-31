"""The 0001_init revision as SQL, rendered offline (`alembic upgrade head --sql`). No database.

The names are compared with what `Base.metadata` declares, so a model change without a revision shows here even
on a machine with no Postgres. The live comparison (`alembic check`) is tests/e2e/test_db_migrations.py.
"""

import importlib
import io
import re
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config import get_settings
from app.core.db import Base
from app.models import AccountRoleType, FileType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
REVISION_FILE = REPO_ROOT / "migrations" / "versions" / "0001_init.py"


@pytest.fixture(autouse=True)
def offline_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # `.invalid` never resolves, so a connection attempt would fail the test.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://nobody@offline.invalid/none"
    )
    get_settings.cache_clear()


def render(*, upgrade: bool) -> str:
    output = io.StringIO()
    config = Config(str(ALEMBIC_INI), output_buffer=output)
    if upgrade:
        command.upgrade(config, "head", sql=True)
    else:
        command.downgrade(config, "0001_init:base", sql=True)
    return output.getvalue()


def names(pattern: str, sql: str) -> set[str]:
    return set(re.findall(pattern, sql))


def tables() -> list[str]:
    importlib.import_module("app.models")
    return sorted(Base.metadata.tables)


def test_the_history_has_one_head_and_it_is_the_initial_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))

    assert script.get_heads() == ["0001_init"]
    revision = script.get_revision("0001_init")
    assert revision is not None
    assert revision.down_revision is None


def test_the_docstring_carries_the_rollback_note() -> None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    revision = script.get_revision("0001_init")
    assert revision is not None

    docstring = revision.module.__doc__

    assert docstring is not None
    assert "Rollback" in docstring
    assert "postgis" in docstring


def test_the_revision_is_frozen_and_imports_nothing_from_the_app() -> None:
    source = REVISION_FILE.read_text()

    assert re.search(r"^\s*(from|import)\s+app\b", source, re.MULTILINE) is None


def test_upgrade_creates_exactly_the_tables_of_the_models() -> None:
    assert names(r'CREATE TABLE "([^"]+)"', render(upgrade=True)) == set(tables())


def test_upgrade_creates_exactly_the_primary_keys_of_the_models() -> None:
    assert names(r'CONSTRAINT "([^"]+)" PRIMARY KEY', render(upgrade=True)) == {
        f"{table}_pkey" for table in tables()
    }


def test_upgrade_creates_exactly_the_indexes_of_the_models() -> None:
    importlib.import_module("app.models")
    expected = {
        str(index.name)
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }

    assert (
        names(r'CREATE (?:UNIQUE )?INDEX "([^"]+)"', render(upgrade=True)) == expected
    )


def test_upgrade_creates_exactly_the_unique_indexes_of_the_models() -> None:
    importlib.import_module("app.models")
    expected = {
        str(index.name)
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.unique
    }

    assert names(r'CREATE UNIQUE INDEX "([^"]+)"', render(upgrade=True)) == expected


def test_upgrade_creates_exactly_the_foreign_keys_of_the_models() -> None:
    importlib.import_module("app.models")
    expected = {
        str(fk.name)
        for table in Base.metadata.tables.values()
        for fk in table.foreign_key_constraints
    }

    assert names(r'CONSTRAINT "([^"]+)" FOREIGN KEY', render(upgrade=True)) == expected


def test_upgrade_creates_the_two_enum_types_with_the_labels_of_the_python_enums() -> (
    None
):
    created = dict(
        re.findall(r'CREATE TYPE "([^"]+)" AS ENUM \(([^)]*)\)', render(upgrade=True))
    )

    def labels(members: Sequence[StrEnum]) -> str:
        return ", ".join(f"'{member.value}'" for member in members)

    assert created == {
        "AccountRoleType": labels(list(AccountRoleType)),
        "FileType": labels(list(FileType)),
    }


def test_upgrade_installs_postgis_before_the_types_and_the_types_before_the_tables() -> (
    None
):
    sql = render(upgrade=True)

    extension = sql.index('CREATE EXTENSION IF NOT EXISTS "postgis"')
    first_type = sql.index("CREATE TYPE")
    # Quoted: alembic's own, unquoted, `CREATE TABLE alembic_version` comes first in the output.
    first_table = sql.index('CREATE TABLE "')
    assert extension < first_type < first_table


# Column order of the final Node tables: the init migration with the later ones applied (kan_6: `File.key` and
# `File.status` dropped, `content` added; kan_12: the two reset columns appended to `AccountIdentity`), and without
# the two columns this base drops (ADR-0015). pg_dump prints columns in this physical order, so task 2.5's diff sees it.
NODE_COLUMN_ORDER = {
    "Account": "id createdAt updatedAt deleted lastLoginAt lastAccountRoleId",
    "AccountIdentity": "id accountId hash salt otpHash otpSalt otpExpiresAt refreshToken deleted "
    "resetTokenExpiresAt resetTokenHash",
    "AccountOnRole": "roleId accountId deleted",
    "AccountProfile": "id accountId email phoneNumber isPhoneVerified firstName lastName middleName "
    "dataOfBirth deleted avatarId",
    "AccountRole": "id type deleted",
    "DeletedHistory": "id relationId deletedAt deletedBy",
    "File": "id createdAt updatedAt deleted name mimeType size createdById content",
    "Notification": "id createdAt updatedAt deleted message type",
    "NotificationRecipient": "notificationId accountId deleted",
}


def test_upgrade_creates_the_columns_in_the_order_of_the_node_tables() -> None:
    created: dict[str, str] = {}
    for table, body in re.findall(
        r'CREATE TABLE "([^"]+)" \((.*?)\n\)', render(upgrade=True), re.DOTALL
    ):
        lines = (line.strip() for line in body.split("\n"))
        created[table] = " ".join(
            line.split()[0].strip('"')
            for line in lines
            if line and not line.startswith("CONSTRAINT")
        )

    assert created == NODE_COLUMN_ORDER


def test_upgrade_leaves_out_the_columns_this_base_dropped() -> None:
    sql = render(upgrade=True)
    file_table = sql[sql.index('CREATE TABLE "File"') :].split(");", 1)[0]

    # SSN and is18YearOld: ADR-0015. key and status: replaced by content / removed in the Node repo.
    assert re.search(r"\b(SSN|is18YearOld)\b", sql) is None
    assert re.search(r"\b(key|status)\b", file_table) is None
    assert "content BYTEA" in file_table


def test_downgrade_drops_every_table_and_both_types_and_leaves_postgis() -> None:
    sql = render(upgrade=False)

    assert names(r'DROP TABLE "([^"]+)"', sql) == set(tables())
    assert names(r'DROP TYPE "([^"]+)"', sql) == {"AccountRoleType", "FileType"}
    assert "DROP EXTENSION" not in sql
