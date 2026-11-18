"""Administrative projections and transaction coordination."""

from functools import wraps
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Grievance, GrievanceEscalation, User
from app.modules.cmo import repository as repo
from app.modules.cmo import schemas as dto
from app.modules.enums import GrievanceStatus, UserRole
from app.modules.grievances import workflow


def transactional(function):
    @wraps(function)
    def wrapped(db: Session, *args, **kwargs):
        try:
            result = function(db, *args, **kwargs)
            db.commit()
            return result
        except IntegrityError as exc:
            db.rollback()
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint in {
                "uq_department_assignments_active_grievance",
                "uq_action_taken_reports_pending_grievance",
            }:
                raise workflow.WorkflowConflict(
                    "Conflicting workflow operation; reload and retry."
                ) from None
            raise
        except Exception:
            db.rollback()
            raise

    return wrapped


def require_cmo(user: User):
    if not user.is_active or user.role != UserRole.CMO_ADMIN:
        raise HTTPException(403, "Insufficient permissions.")


def pagination(filters, total):
    return dto.Pagination(
        page=filters.page,
        page_size=filters.page_size,
        total_items=total,
        total_pages=(total + filters.page_size - 1) // filters.page_size,
    )


def summary(row: Grievance) -> dto.WorkSummary:
    values = {
        name: getattr(row, name) for name in dto.WorkSummary.model_fields if name != "overdue"
    }
    return dto.WorkSummary(
        **values,
        overdue=bool(
            row.due_at and row.due_at < workflow.now() and row.status != GrievanceStatus.RESOLVED
        ),
    )


def list_grievances(db: Session, filters, user: User | None = None):
    rows, total = repo.list_work(db, filters, user)
    return dto.WorkPage(items=[summary(row) for row in rows], pagination=pagination(filters, total))


def detail(db: Session, grievance_id: UUID) -> dto.AdminDetail:
    row = repo.admin_grievance(db, grievance_id)
    if row is None:
        raise HTTPException(404, "Grievance not found.")
    assignments = sorted(row.assignments, key=lambda x: (x.assigned_at, x.id))
    current = next((x for x in assignments if x.closed_at is None), None)
    escalations = db.scalars(
        select(GrievanceEscalation)
        .where(GrievanceEscalation.grievance_id == row.id)
        .order_by(GrievanceEscalation.created_at, GrievanceEscalation.id)
    ).all()
    return dto.AdminDetail(
        **summary(row).model_dump(),
        description=row.description,
        citizen=dto.CitizenContact.model_validate(row.citizen),
        current_department=(
            dto.DepartmentInfo.model_validate(row.current_department)
            if row.current_department
            else None
        ),
        current_assignment=dto.AdminAssignment.model_validate(current) if current else None,
        assignments=[dto.AdminAssignment.model_validate(x) for x in assignments],
        history=[
            dto.AdminHistory.model_validate(x)
            for x in sorted(row.history, key=lambda x: (x.created_at, x.id))
        ],
        updates=[
            dto.UpdateView.model_validate(x)
            for x in sorted(row.updates, key=lambda x: (x.created_at, x.id))
        ],
        reports=[
            dto.ReportView.model_validate(x)
            for x in sorted(row.reports, key=lambda x: (x.submitted_at, x.id))
        ],
        attachments=[dto.AttachmentMetadata.model_validate(x) for x in row.attachments],
        escalations=[dto.EscalationView.model_validate(x) for x in escalations],
    )


def list_reports(db: Session, filters):
    rows, total = repo.list_reports(db, filters)
    return dto.ReportPage(
        items=[dto.ReportView.model_validate(x) for x in rows],
        pagination=pagination(filters, total),
    )


@transactional
def mutate(
    db: Session, user: User, grievance_id: UUID, action: str, data, resolution_days: int = 14
):
    require_cmo(user)
    row = workflow.lock_grievance(db, grievance_id)
    if action == "review":
        workflow.transition(
            db, row, GrievanceStatus.UNDER_REVIEW, user, data.remarks, data.visibility
        )
    elif action in ("assign", "reassign"):
        workflow.assign(
            db, row, user, data, reassign=action == "reassign", resolution_days=resolution_days
        )
    elif action == "remarks":
        workflow.operational_update(db, row, user, data.message, data.visibility)
    elif action == "priority":
        workflow.operational_update(
            db, row, user, f"Priority {row.priority.value} -> {data.priority.value}: {data.reason}"
        )
        row.priority = data.priority
    elif action == "escalate":
        workflow.escalate(db, row, user, data)
    elif action == "reopen":
        workflow.reopen(db, row, user, data.reason)
    elif action == "resume":
        workflow.resume(db, row, user, data.remarks, data.visibility)
    else:
        raise ValueError("Unknown workflow action")
    db.flush()
    return detail(db, row.id)


@transactional
def review_report(db: Session, user: User, report_id: UUID, data):
    require_cmo(user)
    row = workflow.review_report(db, report_id, user, data)
    db.flush()
    return detail(db, row.id)
