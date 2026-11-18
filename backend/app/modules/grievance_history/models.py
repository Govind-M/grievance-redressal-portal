from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.modules.enums import GrievanceStatus, UpdateVisibility


class GrievanceHistory(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "grievance_history"
    __table_args__ = (
        Index("ix_grievance_history_grievance_created", "grievance_id", "created_at"),
    )

    grievance_id: Mapped[UUID] = mapped_column(ForeignKey("grievances.id", ondelete="RESTRICT"))
    from_status: Mapped[GrievanceStatus | None] = mapped_column(
        Enum(GrievanceStatus, name="grievance_status")
    )
    to_status: Mapped[GrievanceStatus] = mapped_column(
        Enum(GrievanceStatus, name="grievance_status")
    )
    changed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    remarks: Mapped[str | None] = mapped_column(Text)
    # Status transitions are public-safe; only explicitly approved remark text is public.
    remarks_visibility: Mapped[UpdateVisibility] = mapped_column(
        Enum(UpdateVisibility, name="update_visibility"), server_default=text("'INTERNAL'")
    )

    grievance: Mapped["Grievance"] = relationship(back_populates="history")
    actor: Mapped["User"] = relationship(
        back_populates="history_changes", foreign_keys=[changed_by]
    )


if TYPE_CHECKING:
    from app.db.models import Grievance, User
