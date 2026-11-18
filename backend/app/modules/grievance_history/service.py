"""Audit creation and deliberately public-safe history projection."""

from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db.models import GrievanceHistory, User
from app.modules.enums import GrievanceStatus, UpdateVisibility, UserRole
from app.modules.grievance_history.schemas import ActorLabel, PublicHistoryEntry

SUBMISSION_REMARK = "Grievance submitted by citizen"
ACTOR_LABELS: dict[UserRole, ActorLabel] = {
    UserRole.CITIZEN: "Citizen",
    UserRole.CMO_ADMIN: "Chief Minister's Office",
    UserRole.DEPARTMENT_OFFICER: "Department Officer",
}


def add_initial_history(db: Session, grievance_id: UUID, citizen_id: UUID) -> None:
    # The caller owns flushing/committing both the grievance and this audit entry.
    db.add(
        GrievanceHistory(
            grievance_id=grievance_id,
            from_status=None,
            to_status=GrievanceStatus.SUBMITTED,
            changed_by=citizen_id,
            remarks=SUBMISSION_REMARK,
            remarks_visibility=UpdateVisibility.PUBLIC,
        )
    )


def public_history(db: Session, grievance_id: UUID) -> list[PublicHistoryEntry]:
    rows = db.execute(
        select(
            GrievanceHistory.from_status,
            GrievanceHistory.to_status,
            GrievanceHistory.created_at,
            case(
                (
                    GrievanceHistory.remarks_visibility == UpdateVisibility.PUBLIC,
                    GrievanceHistory.remarks,
                ),
                else_=None,
            ).label("remarks"),
            User.role,
        )
        .join(User, User.id == GrievanceHistory.changed_by)
        .where(GrievanceHistory.grievance_id == grievance_id)
        .order_by(GrievanceHistory.created_at.asc(), GrievanceHistory.id.asc())
    )
    return [
        PublicHistoryEntry(
            from_status=row.from_status,
            to_status=row.to_status,
            created_at=row.created_at,
            remarks=row.remarks,
            actor_label=ACTOR_LABELS[row.role],
        )
        for row in rows
    ]
