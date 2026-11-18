from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UpdatedAt, UUIDPrimaryKey
from app.modules.enums import UserRole


class User(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(role = 'DEPARTMENT_OFFICER' AND department_id IS NOT NULL) OR "
            "(role IN ('CITIZEN', 'CMO_ADMIN') AND department_id IS NULL)",
            name="role_department",
        ),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    mobile_number: Mapped[str | None] = mapped_column(String(15))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"))
    department_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    department: Mapped["Department | None"] = relationship(back_populates="officers")
    grievances: Mapped[list["Grievance"]] = relationship(
        back_populates="citizen", foreign_keys="Grievance.citizen_id", passive_deletes="all"
    )
    history_changes: Mapped[list["GrievanceHistory"]] = relationship(
        back_populates="actor", foreign_keys="GrievanceHistory.changed_by", passive_deletes="all"
    )
    officer_assignments: Mapped[list["DepartmentAssignment"]] = relationship(
        back_populates="officer",
        foreign_keys="DepartmentAssignment.officer_id",
        passive_deletes="all",
    )
    made_assignments: Mapped[list["DepartmentAssignment"]] = relationship(
        back_populates="assigner",
        foreign_keys="DepartmentAssignment.assigned_by",
        passive_deletes="all",
    )
    updates: Mapped[list["GrievanceUpdate"]] = relationship(
        back_populates="author", passive_deletes="all"
    )
    submitted_reports: Mapped[list["ActionTakenReport"]] = relationship(
        back_populates="submitter",
        foreign_keys="ActionTakenReport.submitted_by",
        passive_deletes="all",
    )
    reviewed_reports: Mapped[list["ActionTakenReport"]] = relationship(
        back_populates="reviewer",
        foreign_keys="ActionTakenReport.reviewed_by",
        passive_deletes="all",
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="uploader", passive_deletes="all"
    )
    feedback: Mapped[list["CitizenFeedback"]] = relationship(
        back_populates="citizen", passive_deletes="all"
    )
    ai_requests: Mapped[list["AIAnalysis"]] = relationship(
        back_populates="requester", passive_deletes="all"
    )
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", passive_deletes="all"
    )


if TYPE_CHECKING:
    from app.db.models import (
        ActionTakenReport,
        AIAnalysis,
        Attachment,
        CitizenFeedback,
        Department,
        DepartmentAssignment,
        Grievance,
        GrievanceHistory,
        GrievanceUpdate,
    )
    from app.modules.auth.models import UserSession
