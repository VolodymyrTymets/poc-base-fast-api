"""DeletedHistory and Migration against the DDL of ../poc-base (init migration). No database."""

import importlib
from typing import Any

import pytest
from sqlalchemy import Column, Table
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import ColumnDefault, CreateIndex, CreateTable, DefaultClause

from app.core.db import Base

POSTGRES = create_async_engine("postgresql+asyncpg://").dialect

TS = "TIMESTAMP(3) WITHOUT TIME ZONE"

# column name -> (compiled type, nullable, server default). Column order is not compared.
COLUMNS: dict[str, dict[str, tuple[str, bool, str | None]]] = {
    "DeletedHistory": {
        "id": ("TEXT", False, None),
        "relationId": ("TEXT", False, None),
        "deletedAt": ("BOOLEAN", False, None),
        "deletedBy": ("TEXT", True, None),
    },
    "Migration": {
        "id": ("TEXT", False, None),
        "name": ("TEXT", False, None),
        "successful": ("BOOLEAN", False, "false"),
        "result": ("TEXT", True, None),
        "description": ("TEXT", True, None),
        "createdAt": (TS, True, "CURRENT_TIMESTAMP"),
        "updatedAt": (TS, True, None),
    },
}


def table(name: str) -> Table:
    # Importing the package is what registers the tables on Base.metadata.
    importlib.import_module("app.models")
    return Base.metadata.tables[name]


def server_default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause), f"{column.name}: unexpected {default!r}"
    return str(default.arg)


@pytest.mark.parametrize("name", COLUMNS)
def test_a_table_has_the_prisma_columns_types_nullability_and_defaults(
    name: str,
) -> None:
    actual = {
        column.name: (
            column.type.compile(dialect=POSTGRES),
            column.nullable,
            server_default(column),
        )
        for column in table(name).columns
    }

    assert actual == COLUMNS[name]


@pytest.mark.parametrize("name", COLUMNS)
def test_a_table_has_the_prisma_primary_key(name: str) -> None:
    primary_key = table(name).primary_key

    assert (primary_key.name, [c.name for c in primary_key.columns]) == (
        f"{name}_pkey",
        ["id"],
    )


def test_deleted_history_has_only_the_relation_id_index() -> None:
    (index,) = table("DeletedHistory").indexes

    assert (index.name, [c.name for c in index.columns], bool(index.unique)) == (
        "DeletedHistory_relationId_idx",
        ["relationId"],
        False,
    )
    assert 'ON "DeletedHistory" ("relationId")' in str(
        CreateIndex(index).compile(dialect=POSTGRES)
    )


def test_migration_has_no_index() -> None:
    assert list(table("Migration").indexes) == []


@pytest.mark.parametrize("name", COLUMNS)
def test_a_table_has_no_foreign_key_and_no_unique_constraint(name: str) -> None:
    uniques = [
        c for c in table(name).constraints if type(c).__name__ == "UniqueConstraint"
    ]

    assert list(table(name).foreign_key_constraints) == []
    assert uniques == []


@pytest.mark.parametrize("name", COLUMNS)
def test_neither_table_has_a_soft_delete_column(name: str) -> None:
    assert "deleted" not in table(name).c


@pytest.mark.parametrize("name", COLUMNS)
def test_create_table_compiles_with_quoted_mixed_case_names(name: str) -> None:
    sql = str(CreateTable(table(name)).compile(dialect=POSTGRES))

    assert sql.startswith(f'\nCREATE TABLE "{name}" (')


def test_migration_updated_at_is_filled_on_insert_and_on_update_like_the_mixin() -> (
    None
):
    # SQLAlchemy wraps each callable per column, so the callables themselves never compare
    # equal; what the mixin guarantees is that a Python callable fills it both times.
    def fills(column: Column[Any]) -> tuple[bool, bool]:
        assert isinstance(column.default, ColumnDefault)
        assert isinstance(column.onupdate, ColumnDefault)
        return column.default.is_callable, column.onupdate.is_callable

    assert fills(table("Migration").c["updatedAt"]) == fills(
        table("Account").c["updatedAt"]
    )
    assert fills(table("Migration").c["updatedAt"]) == (True, True)
