"""Database-backed authentication sessions and consumed/revoked JWT identifiers.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("current_refresh_jti_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_user_sessions_user_id_users"),
        ),
        sa.UniqueConstraint(
            "current_refresh_jti_hash", name=op.f("uq_user_sessions_current_refresh_jti_hash")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_user_sessions_expiry_after_creation")
        ),
        sa.CheckConstraint(
            "length(current_refresh_jti_hash) = 64",
            name=op.f("ck_user_sessions_refresh_hash_length"),
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name=op.f("ck_user_sessions_revocation_metadata"),
        ),
    )
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_index(
        "ix_user_sessions_active_user",
        "user_sessions",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("token_jti_hash", sa.String(64), nullable=False),
        sa.Column("token_type", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revoked_tokens")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["user_sessions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_revoked_tokens_session_id_user_sessions"),
        ),
        sa.UniqueConstraint("token_jti_hash", name=op.f("uq_revoked_tokens_token_jti_hash")),
        sa.CheckConstraint(
            "token_type IN ('access', 'refresh')", name=op.f("ck_revoked_tokens_valid_token_type")
        ),
        sa.CheckConstraint(
            "length(token_jti_hash) = 64", name=op.f("ck_revoked_tokens_jti_hash_length")
        ),
    )
    op.create_index("ix_revoked_tokens_session_id", "revoked_tokens", ["session_id"])
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_session_id", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
    op.drop_index("ix_user_sessions_active_user", table_name="user_sessions")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_table("user_sessions")
