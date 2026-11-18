from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.modules.enums import UpdateVisibility


class GrievanceUpdate(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "grievance_updates"
    __table_args__ = (
        Index("ix_grievance_updates_grievance_created", "grievance_id", "created_at"),
    )

    grievance_id: Mapped[UUID] = mapped_column(ForeignKey("grievances.id", ondelete="RESTRICT"))
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Provenance for department-scoped internal investigation updates.
    assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("department_assignments.id", ondelete="RESTRICT"), index=True
    )
    message: Mapped[str] = mapped_column(Text)
    visibility: Mapped[UpdateVisibility] = mapped_column(
        Enum(UpdateVisibility, name="update_visibility")
    )
    grievance: Mapped["Grievance"] = relationship(back_populates="updates")
    author: Mapped["User"] = relationship(back_populates="updates")


if TYPE_CHECKING:
    from app.db.models import Grievance, User
