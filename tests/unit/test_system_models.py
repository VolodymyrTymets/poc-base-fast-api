"""DeletedHistory against the DDL of ../poc-base (init migration). No database.

The Node `Migration` table is deliberately not mapped (ADR-0018); that the metadata holds no such table is
asserted by the exact table set in test_db_base.py.
"""

import importlib
from typing import Any

from sqlalchemy import Column, Table
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateIndex, CreateTable, DefaultClause

from app.core.db import Base

POSTGRES = create_async_engine("postgresql+asyncpg://").dialect

# column name -> (compiled type, nullable, server default). Column order is pinned by
# test_initial_revision.py, which renders the revision.
DELETED_HISTORY_COLUMNS: dict[str, tuple[str, bool, str | None]] = {
    "id": ("TEXT", False, None),
    "relationId": ("TEXT", False, None),
    "deletedAt": ("BOOLEAN", False, None),
    "deletedBy": ("TEXT", True, None),
}


def deleted_history() -> Table:
    # Importing the package is what registers the tables on Base.metadata.
    importlib.import_module("app.models")
    return Base.metadata.tables["DeletedHistory"]


def server_default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause), f"{column.name}: unexpected {default!r}"
    return str(default.arg)


def test_deleted_history_has_the_prisma_columns_types_nullability_and_defaults() -> (
    None
):
    actual = {
        column.name: (
            column.type.compile(dialect=POSTGRES),
            column.nullable,
            server_default(column),
        )
        for column in deleted_history().columns
    }

    assert actual == DELETED_HISTORY_COLUMNS


def test_deleted_history_has_the_prisma_primary_key() -> None:
    primary_key = deleted_history().primary_key

    assert (primary_key.name, [c.name for c in primary_key.columns]) == (
        "DeletedHistory_pkey",
        ["id"],
    )


def test_deleted_history_has_only_the_relation_id_index() -> None:
    (index,) = deleted_history().indexes

    assert (index.name, [c.name for c in index.columns], bool(index.unique)) == (
        "DeletedHistory_relationId_idx",
        ["relationId"],
        False,
    )
    assert 'ON "DeletedHistory" ("relationId")' in str(
        CreateIndex(index).compile(dialect=POSTGRES)
    )


def test_deleted_history_has_no_foreign_key_and_no_unique_constraint() -> None:
    uniques = [
        c
        for c in deleted_history().constraints
        if type(c).__name__ == "UniqueConstraint"
    ]

    assert list(deleted_history().foreign_key_constraints) == []
    assert uniques == []


def test_deleted_history_has_no_soft_delete_column() -> None:
    assert "deleted" not in deleted_history().c


def test_create_table_compiles_with_quoted_mixed_case_names() -> None:
    sql = str(CreateTable(deleted_history()).compile(dialect=POSTGRES))

    assert sql.startswith('\nCREATE TABLE "DeletedHistory" (')
