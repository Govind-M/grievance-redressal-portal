from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey


class UserSession(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint("length(current_refresh_jti_hash) = 64", name="refresh_hash_length"),
        CheckConstraint(
            "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="revocation_metadata",
        ),
        Index(
            "ix_user_sessions_active_user", "user_id", postgresql_where=text("revoked_at IS NULL")
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    current_refresh_jti_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(100))
    user: Mapped["User"] = relationship(back_populates="sessions")
    revoked_tokens: Mapped[list["RevokedToken"]] = relationship(
        back_populates="session", passive_deletes="all"
    )


class RevokedToken(UUIDPrimaryKey, Base):
    __tablename__ = "revoked_tokens"
    __table_args__ = (
        CheckConstraint("token_type IN ('access', 'refresh')", name="valid_token_type"),
        CheckConstraint("length(token_jti_hash) = 64", name="jti_hash_length"),
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_sessions.id", ondelete="RESTRICT"), index=True
    )
    token_jti_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_type: Mapped[str] = mapped_column(String(10))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str] = mapped_column(String(100))
    session: Mapped["UserSession"] = relationship(back_populates="revoked_tokens")


if TYPE_CHECKING:
    from app.modules.users.models import User
