from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UpdatedAt, UUIDPrimaryKey
from app.modules.enums import GrievanceStatus, Priority


class Grievance(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "grievances"
    __table_args__ = (Index("ix_grievances_district_status", "district", "status"),)

    reference_number: Mapped[str] = mapped_column(String(40), unique=True)
    citizen_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    district: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[GrievanceStatus] = mapped_column(
        Enum(GrievanceStatus, name="grievance_status"),
        server_default=text("'SUBMITTED'"),
        index=True,
    )
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, name="priority"), server_default=text("'MEDIUM'")
    )
    current_department_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Override mixin to add the list/queue timestamp index.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), index=True
    )

    citizen: Mapped["User"] = relationship(back_populates="grievances", foreign_keys=[citizen_id])
    current_department: Mapped["Department | None"] = relationship(
        back_populates="current_grievances"
    )
    history: Mapped[list["GrievanceHistory"]] = relationship(
        back_populates="grievance", passive_deletes="all", order_by="GrievanceHistory.created_at"
    )
    assignments: Mapped[list["DepartmentAssignment"]] = relationship(
        back_populates="grievance", passive_deletes="all"
    )
    updates: Mapped[list["GrievanceUpdate"]] = relationship(
        back_populates="grievance", passive_deletes="all"
    )
    reports: Mapped[list["ActionTakenReport"]] = relationship(
        back_populates="grievance",
        foreign_keys="ActionTakenReport.grievance_id",
        passive_deletes="all",
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="grievance", foreign_keys="Attachment.grievance_id", passive_deletes="all"
    )
    feedback: Mapped[list["CitizenFeedback"]] = relationship(
        back_populates="grievance", passive_deletes="all"
    )
    ai_analyses: Mapped[list["AIAnalysis"]] = relationship(
        back_populates="grievance", passive_deletes="all"
    )


if TYPE_CHECKING:
    from app.db.models import (
        ActionTakenReport,
        AIAnalysis,
        Attachment,
        CitizenFeedback,
        Department,
        DepartmentAssignment,
        GrievanceHistory,
        GrievanceUpdate,
        User,
    )
