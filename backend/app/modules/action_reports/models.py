from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKey
from app.modules.enums import ReviewStatus


class ActionTakenReport(UUIDPrimaryKey, Base):
    __tablename__ = "action_taken_reports"
    __table_args__ = (
        Index(
            "uq_action_taken_reports_pending_grievance",
            "grievance_id",
            unique=True,
            postgresql_where=text("review_status = 'PENDING'"),
        ),
        Index("ix_action_taken_reports_grievance_review", "grievance_id", "review_status"),
        CheckConstraint(
            "(review_status = 'PENDING' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(review_status <> 'PENDING' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="review_metadata",
        ),
        CheckConstraint(
            "reviewed_at IS NULL OR reviewed_at >= submitted_at", name="review_after_submission"
        ),
    )

    grievance_id: Mapped[UUID] = mapped_column(ForeignKey("grievances.id", ondelete="RESTRICT"))
    assignment_id: Mapped[UUID] = mapped_column(
        ForeignKey("department_assignments.id", ondelete="RESTRICT"), index=True
    )
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    report_details: Mapped[str] = mapped_column(Text)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status"), server_default=text("'PENDING'")
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    review_remarks: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    grievance: Mapped["Grievance"] = relationship(
        back_populates="reports", foreign_keys=[grievance_id]
    )
    assignment: Mapped["DepartmentAssignment"] = relationship(
        back_populates="reports", foreign_keys=[assignment_id]
    )
    submitter: Mapped["User"] = relationship(
        back_populates="submitted_reports", foreign_keys=[submitted_by]
    )
    reviewer: Mapped["User | None"] = relationship(
        back_populates="reviewed_reports", foreign_keys=[reviewed_by]
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="report", foreign_keys="Attachment.report_id", passive_deletes="all"
    )


if TYPE_CHECKING:
    from app.db.models import Attachment, DepartmentAssignment, Grievance, User
