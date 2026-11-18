from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.modules.enums import Priority


class GrievanceEscalation(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "grievance_escalations"

    grievance_id: Mapped[UUID] = mapped_column(
        ForeignKey("grievances.id", ondelete="RESTRICT"), index=True
    )
    escalated_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
    previous_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_priority: Mapped[Priority] = mapped_column(Enum(Priority, name="priority"))
    new_priority: Mapped[Priority] = mapped_column(Enum(Priority, name="priority"))
