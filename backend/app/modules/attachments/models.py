from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey


class Attachment(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "attachments"
    __table_args__ = (CheckConstraint("file_size >= 0", name="nonnegative_file_size"),)

    grievance_id: Mapped[UUID] = mapped_column(
        ForeignKey("grievances.id", ondelete="RESTRICT"), index=True
    )
    report_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("action_taken_reports.id", ondelete="RESTRICT"), index=True
    )
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger)

    grievance: Mapped["Grievance"] = relationship(
        back_populates="attachments", foreign_keys=[grievance_id]
    )
    report: Mapped["ActionTakenReport | None"] = relationship(
        back_populates="attachments", foreign_keys=[report_id]
    )
    uploader: Mapped["User"] = relationship(back_populates="attachments")


if TYPE_CHECKING:
    from app.db.models import ActionTakenReport, Grievance, User
