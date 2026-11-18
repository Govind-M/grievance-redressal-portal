from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKey


class DepartmentAssignment(UUIDPrimaryKey, Base):
    __tablename__ = "department_assignments"
    __table_args__ = (
        Index(
            "uq_department_assignments_active_grievance",
            "grievance_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index(
            "ix_department_assignments_active_department",
            "department_id",
            postgresql_where=text("closed_at IS NULL"),
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= assigned_at", name="closed_after_assigned"
        ),
    )

    grievance_id: Mapped[UUID] = mapped_column(
        ForeignKey("grievances.id", ondelete="RESTRICT"), index=True
    )
    department_id: Mapped[UUID] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    officer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    assigned_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assignment_note: Mapped[str | None] = mapped_column(Text)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    grievance: Mapped["Grievance"] = relationship(back_populates="assignments")
    department: Mapped["Department"] = relationship(back_populates="assignments")
    officer: Mapped["User | None"] = relationship(
        back_populates="officer_assignments", foreign_keys=[officer_id]
    )
    assigner: Mapped["User"] = relationship(
        back_populates="made_assignments", foreign_keys=[assigned_by]
    )
    reports: Mapped[list["ActionTakenReport"]] = relationship(
        back_populates="assignment",
        foreign_keys="ActionTakenReport.assignment_id",
        passive_deletes="all",
    )


if TYPE_CHECKING:
    from app.db.models import ActionTakenReport, Department, Grievance, User
