"""Report provenance for advisory AI records; no provider/vector dependency.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_analyses", sa.Column("report_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        None, "ai_analyses", "action_taken_reports", ["report_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_ai_analyses_report_id", "ai_analyses", ["report_id"])


def downgrade():
    op.drop_index("ix_ai_analyses_report_id", table_name="ai_analyses")
    op.drop_constraint(
        "fk_ai_analyses_report_id_action_taken_reports", "ai_analyses", type_="foreignkey"
    )
    op.drop_column("ai_analyses", "report_id")
