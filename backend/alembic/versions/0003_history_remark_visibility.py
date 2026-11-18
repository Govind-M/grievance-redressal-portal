"""Explicit public/private audit remarks; unclassified legacy remarks remain private.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "grievance_history",
        sa.Column(
            "remarks_visibility",
            postgresql.ENUM("PUBLIC", "INTERNAL", name="update_visibility", create_type=False),
            nullable=False,
            server_default=sa.text("'INTERNAL'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("grievance_history", "remarks_visibility")
    # update_visibility belongs to migration 0001 and must not be dropped here.
