"""Tables Account and AccountIdentity. Tasks: 2.2."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.account_profile import AccountProfile
    from app.models.account_role import AccountOnRole, AccountRole
    from app.models.file import File
    from app.models.notification import NotificationRecipient


class Account(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "Account"

    # No default, as in Prisma: whoever creates the account says when it last signed in.
    last_login_at: Mapped[datetime] = mapped_column(
        "lastLoginAt", TIMESTAMP(precision=3)
    )
    last_account_role_id: Mapped[str | None] = mapped_column(
        "lastAccountRoleId",
        Text,
        ForeignKey("AccountRole.id", ondelete="SET NULL", onupdate="CASCADE"),
    )

    identity: Mapped[AccountIdentity | None] = relationship(back_populates="account")
    profile: Mapped[AccountProfile | None] = relationship(back_populates="account")
    account_on_roles: Mapped[list[AccountOnRole]] = relationship(
        back_populates="account"
    )
    last_account_role: Mapped[AccountRole | None] = relationship(
        back_populates="last_role_accounts"
    )
    files: Mapped[list[File]] = relationship(back_populates="created_by")
    notification_recipients: Mapped[list[NotificationRecipient]] = relationship(
        back_populates="account"
    )


# Declared after the class: the descending index needs the mapped column.
Index("Account_createdAt_idx", Account.created_at.desc())


class AccountIdentity(IdMixin, SoftDeleteMixin, Base):
    __tablename__ = "AccountIdentity"

    account_id: Mapped[str] = mapped_column(
        "accountId",
        Text,
        ForeignKey("Account.id", ondelete="RESTRICT", onupdate="CASCADE"),
    )
    hash: Mapped[str | None] = mapped_column(Text)
    salt: Mapped[str | None] = mapped_column(Text)
    otp_hash: Mapped[str | None] = mapped_column("otpHash", Text)
    otp_salt: Mapped[str | None] = mapped_column("otpSalt", Text)
    otp_expires_at: Mapped[datetime | None] = mapped_column(
        "otpExpiresAt", TIMESTAMP(precision=3)
    )
    # sha256 of the password-reset token; the token itself is never stored.
    reset_token_hash: Mapped[str | None] = mapped_column("resetTokenHash", Text)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(
        "resetTokenExpiresAt", TIMESTAMP(precision=3)
    )
    # sha256 of the refresh token, never bcrypt of the whole JWT (rule P5, ADR-0008).
    # The column keeps the Node name `refreshToken` for schema parity.
    refresh_token: Mapped[str | None] = mapped_column("refreshToken", Text)

    account: Mapped[Account] = relationship(back_populates="identity")

    __table_args__ = (
        Index("AccountIdentity_accountId_key", "accountId", unique=True),
        Index("AccountIdentity_resetTokenHash_key", "resetTokenHash", unique=True),
        Index("AccountIdentity_deleted_idx", "deleted"),
    )
