"""Optional semantic capability. Install server pgvector before upgrading past 0005.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import context, op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    if not context.is_offline_mode() and not op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')")
    ):
        raise RuntimeError(
            "pgvector server extension is unavailable. Install pgvector for this PostgreSQL "
            "instance, then upgrade head. Mandatory AI analysis works at revision 0005."
        )
    # Reuse any installed namespace (Supabase commonly uses extensions). Never relocate it.
    # Runtime discovery also keeps offline SQL correct and preserves a caller's current schema.
    op.execute("""
        DO $vector_setup$
        DECLARE vector_schema text; app_schema text := current_schema();
        BEGIN
            SELECT n.nspname INTO vector_schema
            FROM pg_catalog.pg_extension e JOIN pg_catalog.pg_namespace n
                ON n.oid=e.extnamespace WHERE e.extname='vector';
            IF vector_schema IS NULL THEN
                IF EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='extensions') THEN
                    CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
                ELSE
                    CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
                END IF;
                SELECT n.nspname INTO vector_schema
                FROM pg_catalog.pg_extension e JOIN pg_catalog.pg_namespace n
                    ON n.oid=e.extnamespace WHERE e.extname='vector';
            END IF;
            PERFORM pg_catalog.set_config('search_path',
                pg_catalog.quote_ident(app_schema) || ',' || pg_catalog.quote_ident(vector_schema), true);
        END
        $vector_setup$;
    """)
    op.create_table(
        "grievance_embeddings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "grievance_id",
            sa.UUID(),
            sa.ForeignKey("grievances.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(150), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("grievance_id", "model_name", "dimensions"),
        sa.CheckConstraint("dimensions = 768", name="supported_dimensions"),
        sa.CheckConstraint("length(source_fingerprint) = 64", name="fingerprint_length"),
    )
    op.create_index(
        "ix_grievance_embeddings_grievance_id", "grievance_embeddings", ["grievance_id"]
    )


def downgrade():
    op.drop_table("grievance_embeddings")
    # Deliberately retain the extension: other schemas/applications may depend on it.
