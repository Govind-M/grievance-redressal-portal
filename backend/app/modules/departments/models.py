from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey


class Department(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(150), unique=True)
    description: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    officers: Mapped[list["User"]] = relationship(
        back_populates="department", passive_deletes="all"
    )
    assignments: Mapped[list["DepartmentAssignment"]] = relationship(
        back_populates="department", passive_deletes="all"
    )
    current_grievances: Mapped[list["Grievance"]] = relationship(
        back_populates="current_department", passive_deletes="all"
    )
    ai_suggestions: Mapped[list["AIAnalysis"]] = relationship(
        back_populates="suggested_department", passive_deletes="all"
    )


if TYPE_CHECKING:
    from app.db.models import AIAnalysis, DepartmentAssignment, Grievance, User
