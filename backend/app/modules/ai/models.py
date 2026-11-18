from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.modules.enums import Priority


class AIAnalysis(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "ai_analyses"

    grievance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("grievances.id", ondelete="RESTRICT"), index=True
    )
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    model_name: Mapped[str] = mapped_column(String(150))
    analysis_type: Mapped[str] = mapped_column(String(100))
    suggested_department_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT")
    )
    suggested_category: Mapped[str | None] = mapped_column(String(100))
    suggested_priority: Mapped[Priority | None] = mapped_column(Enum(Priority, name="priority"))
    summary: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    grievance: Mapped["Grievance | None"] = relationship(back_populates="ai_analyses")
    requester: Mapped["User | None"] = relationship(back_populates="ai_requests")
    suggested_department: Mapped["Department | None"] = relationship(
        back_populates="ai_suggestions"
    )


if TYPE_CHECKING:
    from app.db.models import Department, Grievance, User
