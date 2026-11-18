"""Optional pgvector table; mandatory AI analysis works without migration 0006."""

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPrimaryKey

EMBEDDING_DIMENSIONS = 768


class GrievanceEmbedding(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "grievance_embeddings"
    __table_args__ = (
        UniqueConstraint("grievance_id", "model_name", "dimensions"),
        CheckConstraint("dimensions = 768", name="supported_dimensions"),
        CheckConstraint("length(source_fingerprint) = 64", name="fingerprint_length"),
    )
    grievance_id: Mapped[UUID] = mapped_column(
        ForeignKey("grievances.id", ondelete="RESTRICT"), index=True
    )
    model_name: Mapped[str] = mapped_column(String(150))
    dimensions: Mapped[int]
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
