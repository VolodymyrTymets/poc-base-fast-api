"""AccountRoleType, tables AccountRole and AccountOnRole. Tasks: 2.2."""

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, IdMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.account import Account


class AccountRoleType(enum.StrEnum):
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"


class AccountRole(IdMixin, SoftDeleteMixin, Base):
    __tablename__ = "AccountRole"

    type: Mapped[AccountRoleType] = mapped_column(
        Enum(AccountRoleType, name="AccountRoleType")
    )

    AccountOnRole: Mapped[list[AccountOnRole]] = relationship(
        "AccountOnRole", back_populates="AccountRole"
    )
    # Prisma's own lower-case name: the accounts whose last used role this is.
    accounts: Mapped[list[Account]] = relationship(
        "Account", back_populates="LastAccountRole"
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

    AccountRole: Mapped[AccountRole] = relationship(
        "AccountRole", back_populates="AccountOnRole"
    )
    Account: Mapped[Account] = relationship("Account", back_populates="AccountOnRole")

    __table_args__ = (Index("AccountOnRole_deleted_idx", "deleted"),)
