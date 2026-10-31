"""AccountRoleType, tables AccountRole and AccountOnRole. Tasks: 2.2."""

import enum

from sqlalchemy import Enum, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, SoftDeleteMixin


class AccountRoleType(enum.StrEnum):
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"


class AccountRole(IdMixin, SoftDeleteMixin, Base):
    __tablename__ = "AccountRole"

    type: Mapped[AccountRoleType] = mapped_column(
        Enum(AccountRoleType, name="AccountRoleType")
    )

    # Prisma makes a unique with CREATE UNIQUE INDEX, not a UNIQUE constraint, so the
    # parity diff of task 2.5 stays empty; the names are written out because the
    # naming convention would call a unique index `_idx`.
    __table_args__ = (
        Index("AccountRole_type_key", "type", unique=True),
        Index("AccountRole_type_deleted_idx", "type", "deleted"),
    )


class AccountOnRole(SoftDeleteMixin, Base):
    __tablename__ = "AccountOnRole"

    # The primary key is the pair; the table has no id column (Prisma `@@id`).
    role_id: Mapped[str] = mapped_column(
        "roleId",
        Text,
        ForeignKey("AccountRole.id", ondelete="RESTRICT", onupdate="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        Text,
        ForeignKey("Account.id", ondelete="RESTRICT", onupdate="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (Index("AccountOnRole_deleted_idx", "deleted"),)
