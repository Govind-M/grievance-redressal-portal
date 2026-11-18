"""Locked lifecycle operations. The caller owns the complete request transaction."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import may_modify_assignment
from app.db.models import (
    ActionTakenReport,
    Department,
    DepartmentAssignment,
    Grievance,
    GrievanceHistory,
    GrievanceUpdate,
    User,
)
from app.modules.enums import GrievanceStatus as Status
from app.modules.enums import Priority, ReviewStatus, UpdateVisibility, UserRole
from app.modules.escalations.models import GrievanceEscalation


class WorkflowConflict(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=409, detail=detail)


TRANSITIONS = {
    Status.SUBMITTED: {Status.UNDER_REVIEW},
    Status.UNDER_REVIEW: {Status.IN_PROGRESS},
    Status.IN_PROGRESS: {Status.RESOLVED},
    Status.RESOLVED: {Status.REOPENED},
    Status.REOPENED: {Status.IN_PROGRESS},
}


def now() -> datetime:
    return datetime.now(UTC)


def lock_grievance(db: Session, grievance_id: UUID) -> Grievance:
    row = db.scalar(
        select(Grievance)
        .where(Grievance.id == grievance_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "Grievance not found.")
    return row


def transition(
    db: Session,
    row: Grievance,
    target: Status,
    user: User,
    remarks: str | None = None,
    visibility: UpdateVisibility = UpdateVisibility.INTERNAL,
) -> None:
    if user.role != UserRole.CMO_ADMIN:
        raise HTTPException(403, "Only CMO may change official status.")
    if target not in TRANSITIONS[row.status]:
        raise WorkflowConflict(f"Cannot transition {row.status.value} to {target.value}.")
    if target in (Status.IN_PROGRESS, Status.RESOLVED):
        assignment = active_assignment(db, row.id)
        if not assignment or assignment.department_id != row.current_department_id:
            raise WorkflowConflict("A consistent active assignment is required.")
        if (
            target == Status.RESOLVED
            and db.scalar(
                select(ActionTakenReport.id)
                .where(
                    ActionTakenReport.grievance_id == row.id,
                    ActionTakenReport.assignment_id == assignment.id,
                    ActionTakenReport.review_status == ReviewStatus.ACCEPTED,
                )
                .limit(1)
            )
            is None
        ):
            raise WorkflowConflict("An accepted report from the active assignment is required.")
    db.add(
        GrievanceHistory(
            grievance_id=row.id,
            from_status=row.status,
            to_status=target,
            changed_by=user.id,
            remarks=remarks,
            remarks_visibility=visibility,
            created_at=now(),
        )
    )
    row.status = target
    row.updated_at = now()


def active_assignment(db: Session, grievance_id: UUID) -> DepartmentAssignment | None:
    return db.scalar(
        select(DepartmentAssignment).where(
            DepartmentAssignment.grievance_id == grievance_id,
            DepartmentAssignment.closed_at.is_(None),
        )
    )


def pending_report(db: Session, grievance_id: UUID) -> bool:
    return (
        db.scalar(
            select(ActionTakenReport.id)
            .where(
                ActionTakenReport.grievance_id == grievance_id,
                ActionTakenReport.review_status == ReviewStatus.PENDING,
            )
            .limit(1)
        )
        is not None
    )


def operational_update(
    db: Session,
    row: Grievance,
    user: User,
    message: str,
    visibility: UpdateVisibility = UpdateVisibility.INTERNAL,
    assignment: DepartmentAssignment | None = None,
) -> GrievanceUpdate:
    update = GrievanceUpdate(
        grievance_id=row.id,
        author_id=user.id,
        message=message,
        visibility=visibility,
        assignment_id=assignment.id if assignment else None,
        created_at=now(),
    )
    db.add(update)
    row.updated_at = now()
    return update


def assign(
    db: Session, row: Grievance, user: User, data, *, reassign: bool, resolution_days: int
) -> None:
    allowed = (
        {Status.IN_PROGRESS, Status.REOPENED}
        if reassign
        else {Status.UNDER_REVIEW, Status.REOPENED}
    )
    if row.status not in allowed:
        raise WorkflowConflict("Assignment is not allowed in the current status.")
    if pending_report(db, row.id):
        raise WorkflowConflict("Review or return the pending report before reassignment.")
    # Shared locks retain active membership/department validity until this commit.
    department = db.scalar(
        select(Department).where(Department.id == data.department_id).with_for_update(read=True)
    )
    if not department or not department.is_active:
        raise HTTPException(422, "Select an active department.")
    if data.officer_id is not None:
        officer = db.scalar(
            select(User).where(User.id == data.officer_id).with_for_update(read=True)
        )
        if (
            not officer
            or not officer.is_active
            or officer.role != UserRole.DEPARTMENT_OFFICER
            or officer.department_id != department.id
        ):
            raise HTTPException(422, "Select an active officer belonging to that department.")
    previous = active_assignment(db, row.id)
    if previous and not reassign:
        raise WorkflowConflict("An active assignment exists; use reassign.")
    if previous:
        previous.closed_at = now()
        db.flush()  # release partial unique key before inserting its successor
    assignment = DepartmentAssignment(
        grievance_id=row.id,
        department_id=department.id,
        officer_id=data.officer_id,
        assigned_by=user.id,
        assignment_note=data.assignment_note,
        assigned_at=now(),
    )
    db.add(assignment)
    row.current_department_id = department.id
    if data.priority is not None:
        row.priority = data.priority
    if row.due_at is None:
        row.due_at = now() + timedelta(days=resolution_days)
    if row.status == Status.UNDER_REVIEW:
        transition(db, row, Status.IN_PROGRESS, user, "Department assigned")
    operational_update(
        db, row, user, f"{'Reassignment' if reassign else 'Assignment'}: {data.assignment_note}"
    )


def officer_assignment(
    db: Session, row: Grievance, user: User, *, modify: bool = False
) -> DepartmentAssignment:
    assignment = active_assignment(db, row.id)
    if (
        not assignment
        or assignment.department_id != user.department_id
        or not user.department
        or not user.department.is_active
        or not user.is_active
        or user.role != UserRole.DEPARTMENT_OFFICER
    ):
        raise HTTPException(404, "Grievance not found.")
    if modify and not may_modify_assignment(user, assignment):
        raise HTTPException(403, "This grievance is assigned to another officer.")
    if modify and row.status != Status.IN_PROGRESS:
        raise WorkflowConflict("Investigation requires IN_PROGRESS status.")
    return assignment


def submit_report(db: Session, row: Grievance, user: User, details: str) -> ActionTakenReport:
    assignment = officer_assignment(db, row, user, modify=True)
    if pending_report(db, row.id):
        raise WorkflowConflict("A report is already pending review.")
    report = ActionTakenReport(
        grievance_id=row.id,
        assignment_id=assignment.id,
        submitted_by=user.id,
        report_details=details,
        review_status=ReviewStatus.PENDING,
        submitted_at=now(),
    )
    db.add(report)
    operational_update(db, row, user, "Action-taken report submitted", assignment=assignment)
    return report


def review_report(db: Session, report_id: UUID, user: User, data) -> Grievance:
    # Discover only the lock key first; every writer locks grievance before report.
    grievance_id = db.scalar(
        select(ActionTakenReport.grievance_id).where(ActionTakenReport.id == report_id)
    )
    if grievance_id is None:
        raise HTTPException(404, "Report not found.")
    row = lock_grievance(db, grievance_id)
    report = db.scalar(
        select(ActionTakenReport)
        .where(ActionTakenReport.id == report_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assignment = active_assignment(db, row.id)
    if report.review_status != ReviewStatus.PENDING:
        raise WorkflowConflict("Report has already been reviewed.")
    if row.status != Status.IN_PROGRESS or not assignment or assignment.id != report.assignment_id:
        raise WorkflowConflict("Report does not belong to the active investigation.")
    report.review_status = ReviewStatus(data.decision)
    report.reviewed_by = user.id
    report.reviewed_at = now()
    report.review_remarks = data.review_remarks
    operational_update(db, row, user, f"Report {data.decision}: {data.review_remarks}")
    if report.review_status == ReviewStatus.ACCEPTED:
        transition(db, row, Status.RESOLVED, user, "Action-taken report accepted")
        row.resolved_at = now()
        assignment.closed_at = now()
    return row


def reopen(db: Session, row: Grievance, user: User, reason: str) -> None:
    if row.status != Status.RESOLVED:
        raise WorkflowConflict("Only resolved grievances may be reopened.")
    # Also close legacy open assignments: old authority never survives a resolution cycle.
    assignment = active_assignment(db, row.id)
    if assignment:
        assignment.closed_at = now()
    transition(db, row, Status.REOPENED, user, reason)
    row.resolved_at = None  # accepted report + immutable history retain prior resolution
    row.due_at = None


def resume(
    db: Session,
    row: Grievance,
    user: User,
    remark: str | None,
    visibility: UpdateVisibility = UpdateVisibility.INTERNAL,
) -> None:
    if row.status != Status.REOPENED:
        raise WorkflowConflict("Only reopened grievances may be resumed.")
    assignment = active_assignment(db, row.id)
    if not assignment or not assignment.department.is_active:
        raise WorkflowConflict("Create a valid assignment using assign/reassign before resuming.")
    if assignment.officer_id is not None and (
        not assignment.officer.is_active
        or assignment.officer.role != UserRole.DEPARTMENT_OFFICER
        or assignment.officer.department_id != assignment.department_id
    ):
        raise WorkflowConflict("Assigned officer is no longer eligible; reassign first.")
    transition(db, row, Status.IN_PROGRESS, user, remark, visibility)


def escalate(db: Session, row: Grievance, user: User, data) -> None:
    if row.status == Status.RESOLVED:
        raise WorkflowConflict("Reopen the grievance before escalating.")
    ranks = {Priority.LOW: 0, Priority.MEDIUM: 1, Priority.HIGH: 2}
    if data.priority is not None and ranks[data.priority] < ranks[row.priority]:
        raise WorkflowConflict("Escalation cannot decrease priority.")
    if data.new_deadline is not None and data.new_deadline <= now():
        raise HTTPException(422, "New deadline must be in the future.")
    db.add(
        GrievanceEscalation(
            grievance_id=row.id,
            escalated_by=user.id,
            reason=data.reason,
            previous_due_at=row.due_at,
            new_due_at=data.new_deadline or row.due_at,
            previous_priority=row.priority,
            new_priority=data.priority or row.priority,
            created_at=now(),
        )
    )
    if data.new_deadline is not None:
        row.due_at = data.new_deadline
    if data.priority is not None:
        row.priority = data.priority
    row.updated_at = now()
