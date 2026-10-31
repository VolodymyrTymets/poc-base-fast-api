"""Tables Notification and NotificationRecipient. Tasks: 2.3."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.account import Account


class Notification(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "Notification"

    message: Mapped[str] = mapped_column(Text)
    # A free string in the Node schema too (its own todo is to make it an enum); no enum is invented here.
    type: Mapped[str] = mapped_column(Text)

    notification_recipients: Mapped[list[NotificationRecipient]] = relationship(
        back_populates="notification"
    )


class NotificationRecipient(SoftDeleteMixin, Base):
    __tablename__ = "NotificationRecipient"

    # The primary key is the pair; the table has no id column (Prisma `@@id`), as in AccountOnRole.
    notification_id: Mapped[str] = mapped_column(
        "notificationId",
        Text,
        ForeignKey("Notification.id", ondelete="RESTRICT", onupdate="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        Text,
        ForeignKey("Account.id", ondelete="RESTRICT", onupdate="CASCADE"),
        primary_key=True,
    )

    notification: Mapped[Notification] = relationship(
        back_populates="notification_recipients"
    )
    account: Mapped[Account] = relationship(back_populates="notification_recipients")
