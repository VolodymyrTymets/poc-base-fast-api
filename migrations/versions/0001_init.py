"""Initial schema: the final state of the four Prisma migrations of the Node base.

Revision ID: 0001_init
Revises: (none)

Folded in, in the Node repo's order: `20260917083733_init`, `20260918115126_kan_6_postgres_file_storage`
(`File.key` replaced by `File.content`, a bytea), `20260918130652_kan_6_drop_file_status` (no `FileStatus`
enum, no `File.status`) and `20260921070817_kan_12_password_auth` (reset-token columns and the unique email).
The one deliberate difference from the Node schema: `AccountProfile` has no `SSN` or `is18YearOld` column
(ADR-0015).

This file is frozen: it names every table and column itself and imports nothing from `app`, so a later change
to a model cannot change what this revision builds. Any schema change is a new revision.

Rollback: `alembic downgrade base` drops the ten tables (their indexes and foreign keys go with them) and the
`AccountRoleType` and `FileType` enum types. It leaves the `postgis` extension installed, because other objects
in the database may depend on it. The rows in the dropped tables are gone for good, so dump a database that
holds data before downgrading it.
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `timestamp(3) without time zone`, as Prisma's DateTime is created.
TIMESTAMP_3 = postgresql.TIMESTAMP(precision=3)

# The types are created and dropped by the SQL below, so the columns must not try to.
account_role_type = postgresql.ENUM(
    "CUSTOMER", "ADMIN", name="AccountRoleType", create_type=False
)


def id_column() -> sa.Column[str]:
    return sa.Column("id", sa.Text(), nullable=False)


def deleted_column() -> sa.Column[bool]:
    return sa.Column(
        "deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False
    )


def created_at_column() -> sa.Column[datetime]:
    return sa.Column(
        "createdAt",
        TIMESTAMP_3,
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def updated_at_column() -> sa.Column[datetime]:
    return sa.Column("updatedAt", TIMESTAMP_3, nullable=True)


def foreign_key(
    table: str, column: str, target: str, *, on_delete: str
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=f"{table}_{column}_fkey",
        ondelete=on_delete,
        onupdate="CASCADE",
    )


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "postgis"')
    op.execute("CREATE TYPE \"AccountRoleType\" AS ENUM ('CUSTOMER', 'ADMIN')")
    op.execute("CREATE TYPE \"FileType\" AS ENUM ('IMG', 'VIDEO')")

    op.create_table(
        "AccountRole",
        id_column(),
        sa.Column("type", account_role_type, nullable=False),
        deleted_column(),
        sa.PrimaryKeyConstraint("id", name="AccountRole_pkey"),
    )
    op.create_index("AccountRole_type_key", "AccountRole", ["type"], unique=True)
    op.create_index("AccountRole_type_deleted_idx", "AccountRole", ["type", "deleted"])

    op.create_table(
        "Account",
        id_column(),
        created_at_column(),
        updated_at_column(),
        deleted_column(),
        sa.Column("lastLoginAt", TIMESTAMP_3, nullable=False),
        sa.Column("lastAccountRoleId", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="Account_pkey"),
        foreign_key(
            "Account", "lastAccountRoleId", "AccountRole", on_delete="SET NULL"
        ),
    )
    op.create_index("Account_createdAt_idx", "Account", [sa.text('"createdAt" DESC')])

    op.create_table(
        "AccountOnRole",
        sa.Column("roleId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        deleted_column(),
        sa.PrimaryKeyConstraint("roleId", "accountId", name="AccountOnRole_pkey"),
        foreign_key("AccountOnRole", "roleId", "AccountRole", on_delete="RESTRICT"),
        foreign_key("AccountOnRole", "accountId", "Account", on_delete="RESTRICT"),
    )
    op.create_index("AccountOnRole_deleted_idx", "AccountOnRole", ["deleted"])

    op.create_table(
        "AccountIdentity",
        id_column(),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=True),
        sa.Column("salt", sa.Text(), nullable=True),
        sa.Column("otpHash", sa.Text(), nullable=True),
        sa.Column("otpSalt", sa.Text(), nullable=True),
        sa.Column("otpExpiresAt", TIMESTAMP_3, nullable=True),
        # sha256 of the refresh token and of the reset token, never the tokens (rule P5).
        sa.Column("refreshToken", sa.Text(), nullable=True),
        deleted_column(),
        # Last, in this order: the Node `kan_12_password_auth` migration appended them to the existing
        # table, and pg_dump (the parity diff of task 2.5) prints columns in their physical order.
        sa.Column("resetTokenExpiresAt", TIMESTAMP_3, nullable=True),
        sa.Column("resetTokenHash", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="AccountIdentity_pkey"),
        foreign_key("AccountIdentity", "accountId", "Account", on_delete="RESTRICT"),
    )
    op.create_index(
        "AccountIdentity_accountId_key", "AccountIdentity", ["accountId"], unique=True
    )
    op.create_index(
        "AccountIdentity_resetTokenHash_key",
        "AccountIdentity",
        ["resetTokenHash"],
        unique=True,
    )
    op.create_index("AccountIdentity_deleted_idx", "AccountIdentity", ["deleted"])

    op.create_table(
        "File",
        id_column(),
        created_at_column(),
        updated_at_column(),
        deleted_column(),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("mimeType", sa.Text(), nullable=True),
        sa.Column("size", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("createdById", sa.Text(), nullable=False),
        # The bytes live in Postgres (ADR-0009).
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="File_pkey"),
        foreign_key("File", "createdById", "Account", on_delete="RESTRICT"),
    )
    op.create_index(
        "File_createdAt_mimeType_idx",
        "File",
        [sa.text('"createdAt" DESC'), "mimeType"],
    )

    op.create_table(
        "AccountProfile",
        id_column(),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phoneNumber", sa.Text(), nullable=True),
        sa.Column(
            "isPhoneVerified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("firstName", sa.Text(), nullable=True),
        sa.Column("lastName", sa.Text(), nullable=True),
        sa.Column("middleName", sa.Text(), nullable=True),
        # The Node column is spelled "dataOfBirth"; the name stays for schema parity (ADR-0004).
        sa.Column("dataOfBirth", sa.Text(), nullable=True),
        deleted_column(),
        sa.Column("avatarId", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="AccountProfile_pkey"),
        foreign_key("AccountProfile", "accountId", "Account", on_delete="RESTRICT"),
        foreign_key("AccountProfile", "avatarId", "File", on_delete="SET NULL"),
    )
    op.create_index(
        "AccountProfile_accountId_key", "AccountProfile", ["accountId"], unique=True
    )
    op.create_index(
        "AccountProfile_email_key", "AccountProfile", ["email"], unique=True
    )
    op.create_index("AccountProfile_deleted_idx", "AccountProfile", ["deleted"])

    op.create_table(
        "Notification",
        id_column(),
        created_at_column(),
        updated_at_column(),
        deleted_column(),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="Notification_pkey"),
    )

    op.create_table(
        "NotificationRecipient",
        sa.Column("notificationId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        deleted_column(),
        sa.PrimaryKeyConstraint(
            "notificationId", "accountId", name="NotificationRecipient_pkey"
        ),
        foreign_key(
            "NotificationRecipient",
            "notificationId",
            "Notification",
            on_delete="RESTRICT",
        ),
        foreign_key(
            "NotificationRecipient", "accountId", "Account", on_delete="RESTRICT"
        ),
    )

    op.create_table(
        "DeletedHistory",
        id_column(),
        sa.Column("relationId", sa.Text(), nullable=False),
        # A flag, not a timestamp, despite the name; kept for schema parity.
        sa.Column("deletedAt", sa.Boolean(), nullable=False),
        sa.Column("deletedBy", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="DeletedHistory_pkey"),
    )
    op.create_index("DeletedHistory_relationId_idx", "DeletedHistory", ["relationId"])

    op.create_table(
        "Migration",
        id_column(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "successful", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        # Nullable, unlike every other createdAt: that is how the Node table was created.
        sa.Column(
            "createdAt",
            TIMESTAMP_3,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        updated_at_column(),
        sa.PrimaryKeyConstraint("id", name="Migration_pkey"),
    )


def downgrade() -> None:
    # Reverse order of creation; a table's indexes and foreign keys go with it.
    for table in (
        "Migration",
        "DeletedHistory",
        "NotificationRecipient",
        "Notification",
        "AccountProfile",
        "File",
        "AccountIdentity",
        "AccountOnRole",
        "Account",
        "AccountRole",
    ):
        op.drop_table(table)

    op.execute('DROP TYPE "FileType"')
    op.execute('DROP TYPE "AccountRoleType"')
    # The postgis extension is left in place (see the module docstring).
