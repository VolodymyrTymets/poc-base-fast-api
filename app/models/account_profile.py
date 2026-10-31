"""Table AccountProfile. Tasks: 2.2."""

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, SoftDeleteMixin


class AccountProfile(IdMixin, SoftDeleteMixin, Base):
    __tablename__ = "AccountProfile"

    account_id: Mapped[str] = mapped_column(
        "accountId",
        Text,
        ForeignKey("Account.id", ondelete="RESTRICT", onupdate="CASCADE"),
    )
    # Login identifier for password accounts; the service stores it trimmed and lowercased.
    email: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column("phoneNumber", Text)
    is_phone_verified: Mapped[bool] = mapped_column(
        "isPhoneVerified", default=False, server_default=text("false")
    )
    first_name: Mapped[str | None] = mapped_column("firstName", Text)
    last_name: Mapped[str | None] = mapped_column("lastName", Text)
    middle_name: Mapped[str | None] = mapped_column("middleName", Text)
    # The Node column is spelled "dataOfBirth"; the name stays for schema parity (ADR-0004)
    # and only the Python attribute is spelled correctly. It holds text, not a date.
    date_of_birth: Mapped[str | None] = mapped_column("dataOfBirth", Text)
    ssn: Mapped[str | None] = mapped_column("SSN", Text)
    is_18_year_old: Mapped[bool] = mapped_column(
        "is18YearOld", default=False, server_default=text("false")
    )
    # A plain column for now: the foreign key to "File" and the Avatar relationship
    # arrive with task 2.3, which creates the File table.
    avatar_id: Mapped[str | None] = mapped_column("avatarId", Text)

    __table_args__ = (
        Index("AccountProfile_accountId_key", "accountId", unique=True),
        Index("AccountProfile_email_key", "email", unique=True),
        Index("AccountProfile_deleted_idx", "deleted"),
    )
