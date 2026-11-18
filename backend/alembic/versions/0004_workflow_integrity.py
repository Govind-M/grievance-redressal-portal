"""Escalation audit, department update provenance and one pending report.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deliberately fail on conflicting legacy pending reports; never discard evidence.
    op.create_index(
        "uq_action_taken_reports_pending_grievance",
        "action_taken_reports",
        ["grievance_id"],
        unique=True,
        postgresql_where=sa.text("review_status = 'PENDING'"),
    )
    op.add_column("grievance_updates", sa.Column("assignment_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        None,
        "grievance_updates",
        "department_assignments",
        ["assignment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_grievance_updates_assignment_id", "grievance_updates", ["assignment_id"])
    priority = postgresql.ENUM("LOW", "MEDIUM", "HIGH", name="priority", create_type=False)
    op.create_table(
        "grievance_escalations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "grievance_id",
            sa.UUID(),
            sa.ForeignKey("grievances.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "escalated_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("previous_due_at", sa.DateTime(timezone=True)),
        sa.Column("new_due_at", sa.DateTime(timezone=True)),
        sa.Column("previous_priority", priority, nullable=False),
        sa.Column("new_priority", priority, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_grievance_escalations_grievance_id", "grievance_escalations", ["grievance_id"]
    )
    op.execute("""
        CREATE TRIGGER grievance_escalations_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON grievance_escalations
        FOR EACH STATEMENT EXECUTE FUNCTION reject_history_mutation()
    """)


def downgrade() -> None:
    op.drop_table("grievance_escalations")
    op.drop_index("ix_grievance_updates_assignment_id", table_name="grievance_updates")
    op.drop_constraint(
        "fk_grievance_updates_assignment_id_department_assignments",
        "grievance_updates",
        type_="foreignkey",
    )
    op.drop_column("grievance_updates", "assignment_id")
    op.drop_index("uq_action_taken_reports_pending_grievance", table_name="action_taken_reports")
